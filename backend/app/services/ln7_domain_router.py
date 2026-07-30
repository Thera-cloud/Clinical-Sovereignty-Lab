"""LN7 3-tier domain router (B2 / W5 / W10).

Tier 1 static → Tier 2 BGE semantic → Tier 3 BoN (burst only).
Steady-state serves Ollama; pushes adapter intent for next hive_burst.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ln7_domain_router")

SEMANTIC_THRESHOLD = float(os.getenv("LN7_SEMANTIC_ROUTE_THRESHOLD", "0.78"))


async def router_enabled(db_pool) -> bool:
    try:
        from app.services.ln7_feature_flags import flag_enabled

        return await flag_enabled(db_pool, "ENABLE_LN7_DOMAIN_ROUTER", default=False)
    except Exception:
        return os.getenv("ENABLE_LN7_DOMAIN_ROUTER", "").lower() in (
            "1", "true", "yes", "on",
        )


def _cache_key(prompt: str, file_paths: List[str]) -> str:
    blob = prompt + "|" + "|".join(sorted(file_paths or []))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


async def _embed_bge(text: str, cache_key: str) -> Optional[List[float]]:
    """Workers BGE via existing path; Redis cache 24h. Fail → None (skip Tier 2)."""
    try:
        from app.services.ln7_serve_endpoint import _prefix, _redis

        r = _redis()
        redis_key = f"{_prefix()}:ln7:embed:{cache_key}"
        if r:
            cached = r.get(redis_key)
            if cached:
                raw = cached.decode() if isinstance(cached, bytes) else cached
                return json.loads(raw)
    except Exception:
        pass

    vec: Optional[List[float]] = None
    try:
        # Prefer Workers AI / Vectorize embedding helper if present
        from app.services import vectorize_service as vs

        if hasattr(vs, "embed_text"):
            vec = await vs.embed_text(text)
        elif hasattr(vs, "get_embedding"):
            vec = await vs.get_embedding(text)
    except Exception as e:
        logger.info("ln7_domain_router: BGE unavailable, skip Tier 2: %s", e)
        return None

    if vec and r:
        try:
            r.setex(redis_key, 86400, json.dumps(vec))
        except Exception:
            pass
    return vec


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    import math

    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na * nb)


async def _static_domain(
    prompt: str, file_paths: List[str]
) -> Optional[str]:
    """Tier 1: extension / import heuristics."""
    joined = " ".join(file_paths or []).lower() + " " + (prompt or "").lower()
    if any(x in joined for x in (".dart", "flutter", "widget")):
        return "flutter"
    if any(x in joined for x in ("docker", "compose", "nginx")):
        return "infra"
    if any(x in joined for x in ("pytest", "asyncpg", "fastapi", ".py")):
        return "python"
    if any(x in joined for x in ("clinical", "therapeutic", "crisis")):
        return "clinical"
    return None


async def route(
    db_pool,
    *,
    prompt: str,
    file_paths: Optional[List[str]] = None,
    task_hash: str = "",
    burst_active: bool = False,
) -> Dict[str, Any]:
    """Return route decision. Steady-state: ollama + intent push."""
    file_paths = file_paths or []
    result: Dict[str, Any] = {
        "tier": 0,
        "adapter_id": None,
        "engine": "ollama",
        "domain_tag": None,
        "runner_ups": [],
    }
    if not await router_enabled(db_pool):
        return result

    domain = await _static_domain(prompt, file_paths)
    result["domain_tag"] = domain

    adapters: List[Dict[str, Any]] = []
    if db_pool and domain:
        try:
            async with db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT r.revision_id, r.domain_tag, r.serve_weight, r.embedding,
                           COALESCE(w.smoothed_win_rate, 0.5) AS win_rate
                    FROM ln7_revisions r
                    LEFT JOIN ln7_adapter_win_rate w ON w.revision_id = r.revision_id
                    WHERE r.status IN ('shadow', 'active', 'sandbox')
                      AND r.domain_tag = $1
                    ORDER BY r.serve_weight DESC NULLS LAST
                    LIMIT 8
                    """,
                    domain,
                )
            adapters = [dict(x) for x in rows]
        except Exception as e:
            logger.warning("domain adapter query failed: %s", e)

    # Tier 1 exact domain hit
    if adapters:
        top = adapters[0]
        result["tier"] = 1
        result["adapter_id"] = top["revision_id"]
        result["runner_ups"] = [a["revision_id"] for a in adapters[1:3]]
    else:
        # Tier 2 semantic
        ck = _cache_key(prompt, file_paths)
        qvec = await _embed_bge(prompt[:2000], ck)
        if qvec and db_pool:
            try:
                async with db_pool.acquire() as conn:
                    rows = await conn.fetch(
                        """
                        SELECT r.revision_id, r.embedding, r.serve_weight,
                               COALESCE(w.smoothed_win_rate, 0.5) AS win_rate
                        FROM ln7_revisions r
                        LEFT JOIN ln7_adapter_win_rate w ON w.revision_id = r.revision_id
                        WHERE r.embedding IS NOT NULL
                          AND r.status IN ('shadow', 'active', 'sandbox')
                        LIMIT 40
                        """
                    )
                scored: List[Tuple[float, str]] = []
                for row in rows:
                    emb = row["embedding"]
                    if isinstance(emb, str):
                        emb = json.loads(emb)
                    if isinstance(emb, dict) and "vector" in emb:
                        emb = emb["vector"]
                    if not isinstance(emb, list):
                        continue
                    score = _cosine(qvec, emb) * float(row["win_rate"] or 0.5)
                    scored.append((score, row["revision_id"]))
                scored.sort(reverse=True)
                if scored and scored[0][0] >= SEMANTIC_THRESHOLD:
                    result["tier"] = 2
                    result["adapter_id"] = scored[0][1]
                    result["runner_ups"] = [s[1] for s in scored[1:3]]
            except Exception as e:
                logger.info("Tier 2 semantic failed, skip: %s", e)

    # Tier 3 BoN only in burst
    if result["adapter_id"] is None and burst_active and adapters:
        result["tier"] = 3
        result["adapter_id"] = adapters[0]["revision_id"]
        result["runner_ups"] = [a["revision_id"] for a in adapters[1:3]]
        result["engine"] = "vllm_burst"

    if result["adapter_id"]:
        try:
            from app.services.ln7_serve_endpoint import (
                get_serve_endpoint,
                push_adapter_intent,
            )

            push_adapter_intent(result["adapter_id"], task_hash=task_hash)
            ep = get_serve_endpoint()
            if ep and burst_active:
                result["engine"] = "vllm_burst"
                result["endpoint"] = ep
        except Exception:
            pass

    return result

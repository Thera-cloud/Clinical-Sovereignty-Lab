"""LN7 3-tier domain router (B2 / W5 / W10).

Tier 1 static → Tier 2 BGE semantic → Tier 3 BoN (burst only).
Steady-state serves Ollama; pushes adapter intent for next hive_burst.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ln7_domain_router")


def _semantic_threshold() -> float:
    env = os.getenv("LN7_SEMANTIC_ROUTE_THRESHOLD", "").strip()
    if env:
        try:
            return float(env)
        except ValueError:
            pass
    try:
        from app.services.ln7_frozen_config import load_json

        gov = load_json("governance.json", {}) or {}
        return float(gov.get("semantic_route_threshold") or 0.78)
    except Exception:
        return 0.78


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
    r = None
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
        r = None

    vec: Optional[List[float]] = None
    try:
        from app.services import vectorize_service as vs

        if hasattr(vs, "embed_text"):
            vec = await vs.embed_text(text)
        elif hasattr(vs, "get_embedding"):
            vec = await vs.get_embedding(text)
    except Exception as e:
        logger.info("ln7_domain_router: BGE unavailable, skip Tier 2: %s", e)
        return None

    if vec and r is not None:
        try:
            from app.services.ln7_serve_endpoint import _prefix

            r.setex(f"{_prefix()}:ln7:embed:{cache_key}", 86400, json.dumps(vec))
        except Exception:
            pass
    return vec


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na * nb)


def _parse_embedding(emb: Any) -> Optional[List[float]]:
    if isinstance(emb, str):
        try:
            emb = json.loads(emb)
        except Exception:
            return None
    if isinstance(emb, dict) and "vector" in emb:
        emb = emb["vector"]
    if isinstance(emb, list) and emb and all(isinstance(x, (int, float)) for x in emb):
        return [float(x) for x in emb]
    return None


async def _static_domain(
    prompt: str, file_paths: List[str]
) -> Optional[str]:
    """Tier 1: extension / import heuristics (+ pack domain_tag hints)."""
    joined = " ".join(file_paths or []).lower() + " " + (prompt or "").lower()
    # Pack name / path often carries domain after W9 backfill
    for path in file_paths or []:
        try:
            from pathlib import Path

            tj = Path(__file__).resolve().parents[1] / "data" / "ln_sandbox_ci_packs" / Path(path).name / "task.json"
            if not tj.is_file():
                # path may already be pack id
                tj = (
                    Path(__file__).resolve().parents[1]
                    / "data"
                    / "ln_sandbox_ci_packs"
                    / str(path)
                    / "task.json"
                )
            if tj.is_file():
                meta = json.loads(tj.read_text(encoding="utf-8"))
                tag = str(meta.get("domain_tag") or "").strip()
                if tag:
                    return tag
        except Exception:
            pass
    if any(x in joined for x in (".dart", "flutter", "widget")):
        return "flutter"
    if any(x in joined for x in ("docker", "compose", "nginx", "wireguard")):
        return "infra"
    if any(x in joined for x in ("qlora", "lora", "vllm", "ollama")):
        return "ml"
    if any(x in joined for x in ("auditor", "trust_baseline", "trust enforcer")):
        return "trust"
    if any(x in joined for x in ("stripe", "billing", "quickbooks", "token_lab")):
        return "billing"
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
    thresh = _semantic_threshold()
    result: Dict[str, Any] = {
        "tier": 0,
        "adapter_id": None,
        "engine": "ollama",
        "domain_tag": None,
        "runner_ups": [],
        "semantic_threshold": thresh,
        "ok": True,
    }
    if not await router_enabled(db_pool):
        result["skipped"] = True
        result["reason"] = "router_disabled"
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
                    ORDER BY r.serve_weight DESC NULLS LAST,
                             COALESCE(w.smoothed_win_rate, 0.5) DESC
                    LIMIT 8
                    """,
                    domain,
                )
            adapters = [dict(x) for x in rows]
        except Exception as e:
            logger.warning("domain adapter query failed: %s", e)

    scored_global: List[Tuple[float, str]] = []

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
                for row in rows:
                    emb = _parse_embedding(row["embedding"])
                    if not emb:
                        continue
                    score = _cosine(qvec, emb) * float(row["win_rate"] or 0.5)
                    scored_global.append((score, row["revision_id"]))
                scored_global.sort(reverse=True)
                if scored_global and scored_global[0][0] >= thresh:
                    result["tier"] = 2
                    result["adapter_id"] = scored_global[0][1]
                    result["runner_ups"] = [s[1] for s in scored_global[1:3]]
            except Exception as e:
                logger.info("Tier 2 semantic failed, skip: %s", e)

    # Tier 3 BoN only in burst — domain adapters or semantic top-3
    if result["adapter_id"] is None and burst_active:
        pool = adapters or [
            {"revision_id": rid} for _, rid in scored_global[:3]
        ]
        if pool:
            result["tier"] = 3
            result["adapter_id"] = pool[0]["revision_id"]
            result["runner_ups"] = [
                (a.get("revision_id") if isinstance(a, dict) else a)
                for a in pool[1:3]
            ]
            result["engine"] = "vllm_burst"

    if result["adapter_id"]:
        try:
            from app.services.ln7_serve_endpoint import (
                get_serve_endpoint,
                push_adapter_intent,
            )

            push_adapter_intent(result["adapter_id"], task_hash=task_hash)
            for rid in result.get("runner_ups") or []:
                if rid and rid != result["adapter_id"]:
                    push_adapter_intent(str(rid), task_hash=task_hash)
            ep = get_serve_endpoint()
            if ep and burst_active:
                result["engine"] = "vllm_burst"
                result["endpoint"] = ep
        except Exception:
            pass

    return result

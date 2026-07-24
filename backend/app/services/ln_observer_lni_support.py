"""
LN-Observer helpers for LittleNateInference (keeps protected LNI file lean).
# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid as uuid_mod
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ~1800 tokens ≈ 7200 chars at ~4 chars/token
_WISDOM_CHAR_BUDGET = 7200
_WISDOM_CACHE: Optional[str] = None

# Mirror littlenate_inference promotion constants (avoid importing LNI at module load)
_PROMOTION_INCREMENT = 0.03
_PROMOTION_CAP = 0.95


def _wisdom_candidates() -> List[Path]:
    """Resolve Night School wisdom across backend/bridge mounts. # QUANTUM-CRYSTAL-ARCH"""
    data_dir = Path(os.environ.get("DATA_DIR", "/app/data"))
    bridge_dir = Path(os.environ.get("BRIDGE_DATA_DIR", "/app/bridge_data"))
    return [
        data_dir / "Vaults" / "Admin" / "little_nate_wisdom.json",
        bridge_dir / "Vaults" / "Admin" / "little_nate_wisdom.json",
        data_dir.parent / "bridge" / "Vaults" / "Admin" / "little_nate_wisdom.json",
        Path("/opt/clinical-sovereignty-lab/data/bridge/Vaults/Admin/little_nate_wisdom.json"),
    ]


def _wisdom_path() -> Path:
    for p in _wisdom_candidates():
        if p.exists():
            return p
    return _wisdom_candidates()[0]


def load_wisdom_snapshot(char_budget: int = _WISDOM_CHAR_BUDGET) -> str:
    """Fixed-token wisdom excerpt — matches NightSchool.load_wisdom canonical keys."""
    global _WISDOM_CACHE
    if _WISDOM_CACHE is not None:
        return _WISDOM_CACHE
    path = _wisdom_path()
    if not path.exists():
        logger.warning(
            "LN-Observer wisdom file missing (tried %s)",
            [str(p) for p in _wisdom_candidates()],
        )
        _WISDOM_CACHE = ""
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("LN-Observer wisdom load failed: %s", e)
        _WISDOM_CACHE = ""
        return ""

    parts: List[str] = []
    if isinstance(data, dict):
        # Canonical Night School file: accumulated_learnings (+ optional persona keys)
        acc = data.get("accumulated_learnings")
        if isinstance(acc, str) and acc.strip():
            parts.append(acc.strip())
        for key in (
            "persona", "identity", "voice", "modalities", "modality_spine",
            "core_principles", "night_school_core", "system_persona",
        ):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                parts.append(val.strip())
            elif isinstance(val, list):
                parts.extend(str(x).strip() for x in val if str(x).strip())
            elif isinstance(val, dict):
                parts.append(json.dumps(val)[:2000])
        cats = data.get("categories")
        if isinstance(cats, list) and cats:
            parts.append("Categories: " + ", ".join(str(c) for c in cats[:20]))
        if not parts:
            for k, v in list(data.items())[:12]:
                parts.append(
                    f"{k}: {v}" if not isinstance(v, (dict, list))
                    else f"{k}: {json.dumps(v)[:800]}"
                )
    else:
        parts.append(str(data))

    text = "\n\n".join(parts).strip()
    if len(text) > char_budget:
        text = text[:char_budget].rsplit("\n", 1)[0] + "\n[…wisdom excerpt truncated]"
    _WISDOM_CACHE = text
    return text


async def resolve_user_uuid(db_pool, identity: str) -> Optional[str]:
    """Map username / hardware_id → users.id (UUID str) for Vectorize user_id filter."""
    if not db_pool or not identity:
        return None
    # Already a UUID?
    try:
        import uuid as _uuid
        _uuid.UUID(str(identity))
        return str(identity)
    except Exception:
        pass
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id::text AS uid FROM users "
                "WHERE username=$1 OR hardware_id=$1 LIMIT 1",
                identity,
            )
        return row["uid"] if row else None
    except Exception as e:
        logger.warning("LN-Observer resolve_user_uuid(%s): %s", identity, e)
        return None


async def resolve_user_uuids(db_pool, identities: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for ident in identities:
        uid = await resolve_user_uuid(db_pool, ident)
        if uid and uid not in seen:
            seen.add(uid)
            out.append(uid)
    return out


async def _reinforce_recall(db_pool, crystals: List[Dict[str, Any]], limit: int = 10) -> None:
    if not db_pool or not crystals:
        return
    try:
        async with db_pool.acquire() as conn:
            for c in crystals[:limit]:
                _wid = c.get("metadata", {}).get("wisdom_id", "") or ""
                _ch = _wid.replace("crystal_", "") if _wid.startswith("crystal_") else ""
                if not _ch:
                    _ch = (c.get("metadata", {}) or {}).get("content_hash", "")
                    if _ch:
                        _ch = str(_ch)[:16]
                if not _ch:
                    continue
                await conn.execute(
                    f"""
                    UPDATE nate_intelligence_crystals
                    SET recall_count = COALESCE(recall_count, 0) + 1,
                        last_recalled_at = NOW(),
                        confidence = LEAST(
                            COALESCE(confidence, 0.5) + {_PROMOTION_INCREMENT},
                            {_PROMOTION_CAP}
                        ),
                        updated_at = NOW()
                    WHERE LEFT(content_hash, 16) = $1
                    """,
                    _ch,
                )
    except Exception as e:
        logger.debug("LN-Observer recall reinforcement: %s", e)


async def retrieve_crystals_multi(
    query: str,
    primary_user_id: str,
    also_user_ids: Optional[List[str]] = None,
    top_k: int = 8,
    also_top_k: int = 4,
    db_pool=None,
    resolve_ids: bool = True,
) -> List[Dict[str, Any]]:
    """
    Semantic recall with optional cross-client merge. Never filters by origin_surface.
    Resolves usernames → UUID for Vectorize (crystals indexed by users.id).
    Reinforces recall_count / last_recalled_at when db_pool is provided.
    """
    from app.services.vectorize_service import semantic_search_all

    primary = primary_user_id
    also = list(also_user_ids or [])
    if resolve_ids and db_pool:
        resolved_primary = await resolve_user_uuid(db_pool, primary_user_id)
        if resolved_primary:
            primary = resolved_primary
        also = await resolve_user_uuids(db_pool, also)

    async def _one(uid: str, k: int) -> List[Dict[str, Any]]:
        results = await semantic_search_all(query, uid, top_k=k)
        crystals: List[Dict[str, Any]] = []
        for _index, matches in results.items():
            crystals.extend(matches)
        return crystals

    merged: List[Dict[str, Any]] = []
    seen = set()
    try:
        primary_hits = await _one(primary, max(top_k, 8))
        for c in primary_hits:
            h = c.get("metadata", {}).get("content_hash") or c.get("id") or c.get("text", "")[:64]
            if h in seen:
                continue
            seen.add(h)
            merged.append(c)
        for uid in also[:3]:
            if not uid or uid == primary:
                continue
            extra = await _one(uid, also_top_k)
            for c in extra:
                h = c.get("metadata", {}).get("content_hash") or c.get("id") or c.get("text", "")[:64]
                if h in seen:
                    continue
                seen.add(h)
                merged.append(c)
        merged.sort(key=lambda c: c.get("score", 0), reverse=True)
        top = merged[:top_k]
        if not top and db_pool:
            # QUANTUM-CRYSTAL-ARCH — PG keyword fallback when Vectorize cold/empty
            top = await _pg_keyword_crystal_fallback(
                db_pool, query, primary, also, limit=top_k
            )
        await _reinforce_recall(db_pool, top, limit=min(10, top_k))
        return top
    except Exception as e:
        logger.warning("LN-Observer multi-user crystal retrieve failed: %s", e)
        return []


async def _pg_keyword_crystal_fallback(
    db_pool,
    query: str,
    primary_uuid: str,
    also_uuids: List[str],
    limit: int = 8,
) -> List[Dict[str, Any]]:
    """ILIKE fallback for Observer same-brain when Vectorize returns 0 hits."""
    tokens = [
        t for t in re.findall(r"[A-Za-z]{4,}", query or "")
        if t.lower() not in {
            "what", "which", "with", "that", "this", "about", "from",
            "have", "your", "their", "modality", "surface", "night",
            "school", "wisdom", "relevant", "memory", "observe",
        }
    ][:6]
    # Therapeutic anchors when STT/smoke query is short after stopword filter
    for anchor in ("attachment", "rupture", "pursue", "withdraw", "coaching"):
        if anchor not in {t.lower() for t in tokens}:
            tokens.append(anchor)
        if len(tokens) >= 8:
            break
    if not tokens:
        return []
    try:
        ids = []
        for u in [primary_uuid] + list(also_uuids or []):
            try:
                ids.append(uuid_mod.UUID(str(u)))
            except Exception:
                continue
        like_patterns = [f"%{t}%" for t in tokens[:6]]
        async with db_pool.acquire() as conn:
            # Prefer owned user/user:* scopes; global allowlist for ownerless.
            if ids:
                rows = await conn.fetch(
                    """SELECT crystal_text, content_hash, confidence, domain
                       FROM nate_intelligence_crystals
                       WHERE superseded_by IS NULL
                         AND COALESCE(confidence, 0) >= 0.30
                         AND (
                           (
                             user_id = ANY($1::uuid[])
                             AND (
                               scope = 'user'
                               OR scope LIKE 'user:%'
                               OR scope IS NULL
                               OR scope != 'archived'
                             )
                           )
                           OR (user_id IS NULL AND scope = 'global')
                         )
                         AND crystal_text ILIKE ANY($2::text[])
                       ORDER BY
                         CASE WHEN user_id = ANY($1::uuid[]) THEN 0 ELSE 1 END,
                         confidence DESC NULLS LAST,
                         created_at DESC
                       LIMIT $3""",
                    ids,
                    like_patterns,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """SELECT crystal_text, content_hash, confidence, domain
                       FROM nate_intelligence_crystals
                       WHERE superseded_by IS NULL
                         AND COALESCE(confidence, 0) >= 0.30
                         AND user_id IS NULL AND scope = 'global'
                         AND crystal_text ILIKE ANY($1::text[])
                       ORDER BY confidence DESC NULLS LAST, created_at DESC
                       LIMIT $2""",
                    like_patterns,
                    limit,
                )
        out: List[Dict[str, Any]] = []
        for r in rows or []:
            text = (r["crystal_text"] or "").strip()
            if not text:
                continue
            out.append(
                {
                    "text": text,
                    "score": float(r["confidence"] or 0.5),
                    "metadata": {
                        "text": text,
                        "content_hash": r["content_hash"],
                        "domain": r["domain"],
                        "source": "pg_fallback",
                    },
                }
            )
        if out:
            logger.warning(
                "LN-Observer PG crystal fallback hits=%s tokens=%s",
                len(out),
                tokens[:4],
            )
        return out
    except Exception as e:
        logger.warning("LN-Observer PG crystal fallback failed: %s", e)
        return []

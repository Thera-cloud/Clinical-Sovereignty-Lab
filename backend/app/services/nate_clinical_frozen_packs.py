"""QUANTUM-CRYSTAL-ARCH — Snapshot clinical crystals for fair twin bakeoffs."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, Sequence

from app.services.nate_clinical_flags import snapshot_min_confidence, snapshot_top_n

logger = logging.getLogger("nate.clinical_frozen_packs")


async def build_clinical_crystal_snapshot(
    db_pool,
    *,
    top_n: Optional[int] = None,
    min_confidence: Optional[float] = None,
    tag_filter: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Snapshot top clinical crystals → frozen_context_hash + crystal texts."""
    if db_pool is None:
        return {"frozen_context_hash": "empty", "crystals": [], "crystal_ids": []}

    n = top_n if top_n is not None else snapshot_top_n()
    conf = min_confidence if min_confidence is not None else snapshot_min_confidence()
    crystals: List[Dict[str, Any]] = []
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id::text AS id, crystal_text, confidence, recall_count
                FROM nate_intelligence_crystals
                WHERE domain = 'clinical'
                  AND superseded_by IS NULL
                  AND confidence >= $1
                  AND (scope IS NULL OR scope NOT LIKE 'user:%')
                ORDER BY confidence DESC, COALESCE(recall_count, 0) DESC, created_at DESC
                LIMIT $2
                """,
                conf,
                n,
            )
            for r in rows:
                text = (r["crystal_text"] or "").strip()
                if not text:
                    continue
                if tag_filter:
                    low = text.lower()
                    if not any(t.lower() in low for t in tag_filter):
                        continue
                crystals.append(
                    {
                        "id": r["id"],
                        "text": text[:2000],
                        "confidence": float(r["confidence"] or 0),
                    }
                )
    except Exception as e:
        logger.warning("clinical snapshot query failed: %s", e)
        return {"frozen_context_hash": "empty", "crystals": [], "crystal_ids": []}

    ids = [c["id"] for c in crystals]
    payload = json.dumps({"ids": ids, "n": len(ids)}, sort_keys=True)
    fhash = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:48]
    filters = {
        "domain": "clinical",
        "min_confidence": conf,
        "top_n": n,
        "tag_filter": list(tag_filter) if tag_filter else [],
    }
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO nate_clinical_frozen_packs
                    (frozen_context_hash, crystal_ids, filters_json)
                VALUES ($1, $2::jsonb, $3::jsonb)
                ON CONFLICT (frozen_context_hash) DO NOTHING
                """,
                fhash,
                json.dumps(ids),
                json.dumps(filters),
            )
    except Exception as e:
        logger.warning("frozen pack persist skipped: %s", e)

    return {
        "frozen_context_hash": fhash,
        "crystals": crystals,
        "crystal_ids": ids,
        "filters": filters,
    }


def format_frozen_context(crystals: Sequence[Dict[str, Any]]) -> str:
    if not crystals:
        return ""
    parts = ["[FROZEN CLINICAL KNOWLEDGE PACK — identical for both twins]"]
    for i, c in enumerate(crystals[:40], 1):
        parts.append(f"{i}. {c.get('text', '')[:800]}")
    return "\n".join(parts)

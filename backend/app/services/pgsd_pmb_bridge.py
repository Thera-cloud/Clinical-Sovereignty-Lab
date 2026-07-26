"""
PGSD ↔ PMB crisis precursor bridge.  # QUANTUM-CRYSTAL-ARCH

Sole writer for pmb_dict['crisis_precursors']. Never raises into callers.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_MAX_PRECURSORS = 20


def _region_to_precursor(row: Dict[str, Any]) -> Dict[str, Any]:
    created = row.get("created_at")
    if isinstance(created, datetime):
        created = created.isoformat()
    return {
        "source": "pgsd_crisis_region",
        "region_id": row.get("id"),
        "source_event_id": row.get("source_event_id"),
        "centroid": {
            "d1_valence": row.get("d1_valence"),
            "d2_arousal": row.get("d2_arousal"),
            "d3_relational": row.get("d3_relational"),
            "d4_temporal": row.get("d4_temporal"),
            "d5_integration": row.get("d5_integration"),
        },
        "radius": row.get("radius"),
        "detected_at": created,
        "confidence": 0.75,
    }


def merge_crisis_precursors(
    pmb_dict: Dict[str, Any],
    regions: List[Dict[str, Any]],
) -> None:
    """Append PGSD crisis regions into pmb_dict (dedupe by region_id). Never raises."""
    try:
        if not isinstance(pmb_dict, dict):
            return
        existing = pmb_dict.get("crisis_precursors")
        if not isinstance(existing, list):
            existing = []
        seen = {
            p.get("region_id")
            for p in existing
            if isinstance(p, dict) and p.get("region_id") is not None
        }
        for row in regions or []:
            if not isinstance(row, dict):
                continue
            rid = row.get("id")
            if rid is not None and rid in seen:
                continue
            existing.append(_region_to_precursor(row))
            if rid is not None:
                seen.add(rid)
        pmb_dict["crisis_precursors"] = existing[-_MAX_PRECURSORS:]
    except Exception as e:
        logger.debug("pgsd_pmb_bridge merge failed (non-fatal): %s", e)


async def append_crisis_precursor(
    db_pool: Any,
    pmb_dict: Dict[str, Any],
    user_id: str,
) -> None:
    """
    Load nearest pgsd_crisis_regions for user (hardware_id canonical) and merge.
    Never raises.
    """
    try:
        if db_pool is None or not user_id or not isinstance(pmb_dict, dict):
            return
        hw_id = str(user_id).strip()
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, user_id, username,
                       d1_valence, d2_arousal, d3_relational,
                       d4_temporal, d5_integration,
                       radius, source_event_id, created_at
                FROM pgsd_crisis_regions
                WHERE user_id = $1
                ORDER BY created_at DESC
                LIMIT 10
                """,
                hw_id,
            )
        merge_crisis_precursors(pmb_dict, [dict(r) for r in rows])
    except Exception as e:
        logger.debug("append_crisis_precursor failed (non-fatal): %s", e)


async def seed_region_from_crisis_event(
    db_pool: Any,
    crisis_event_id: int,
    *,
    window_hours: float = 2.0,
) -> Optional[int]:
    """
    Optional helper: find nearest pgsd_snapshot ±window around crisis_events row
    and INSERT pgsd_crisis_regions. Returns new region id or None. Never raises.
    """
    try:
        if db_pool is None:
            return None
        async with db_pool.acquire() as conn:
            ev = await conn.fetchrow(
                """
                SELECT id, hardware_id, user_name, timestamp
                FROM crisis_events
                WHERE id = $1
                """,
                int(crisis_event_id),
            )
            if not ev or not ev.get("hardware_id"):
                return None
            hw = ev["hardware_id"]
            ts = ev.get("timestamp")
            snap = await conn.fetchrow(
                """
                SELECT id, username,
                       d1_valence, d2_arousal, d3_relational,
                       d4_temporal_depth AS d4_temporal,
                       d5_integration, coherence
                FROM pgsd_snapshots
                WHERE user_id = $1
                  AND computed_at BETWEEN $2::timestamptz - ($3 || ' hours')::interval
                                      AND $2::timestamptz + ($3 || ' hours')::interval
                ORDER BY ABS(EXTRACT(EPOCH FROM (computed_at - $2::timestamptz)))
                LIMIT 1
                """,
                hw,
                ts,
                str(float(window_hours)),
            )
            if not snap:
                return None
            row = await conn.fetchrow(
                """
                INSERT INTO pgsd_crisis_regions (
                    user_id, username,
                    d1_valence, d2_arousal, d3_relational,
                    d4_temporal, d5_integration,
                    radius, source_event_id
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING id
                """,
                hw,
                snap.get("username"),
                snap.get("d1_valence"),
                snap.get("d2_arousal"),
                snap.get("d3_relational"),
                snap.get("d4_temporal"),
                snap.get("d5_integration"),
                0.25,
                str(crisis_event_id),
            )
            return int(row["id"]) if row else None
    except Exception as e:
        logger.warning("seed_region_from_crisis_event failed: %s", e)
        return None


__all__ = [
    "append_crisis_precursor",
    "merge_crisis_precursors",
    "seed_region_from_crisis_event",
]

"""
PGSD trauma well engine — temporal attractors from snapshots + bridge seeds.  # QUANTUM-CRYSTAL-ARCH

Gated by ENABLE_PGSD_FIELD.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_TEMPORAL_CLASSES = ("past", "present", "future", "inherited")


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def field_enabled() -> bool:
    return _env_true("PGSD_ENABLED") and _env_true("ENABLE_PGSD_FIELD")


def _classify_temporal(d4: Optional[float], source_tag: str) -> str:
    tag = (source_tag or "").lower()
    if "inherit" in tag or "transgener" in tag or "legacy" in tag:
        return "inherited"
    d = float(d4 or 0.0)
    if d < -0.25:
        return "past"
    if d > 0.25:
        return "future"
    return "present"


class TraumaWellEngine:
    def __init__(self, db_pool: Any = None):
        self.db_pool = db_pool

    async def refresh_wells(self, user_id: str) -> List[int]:
        """
        Upsert wells from recent snapshots + sensitive_bridge trigger dates.
        Returns list of well ids touched. Never raises.
        """
        ids: List[int] = []
        try:
            if not field_enabled() or not self.db_pool or not user_id:
                return ids

            from app.services.pgsd_engine import PGSDEngine

            eng = PGSDEngine(db_pool=self.db_pool)
            resolved = await eng.resolve_pgsd_subject(user_id)
            if not resolved:
                return ids
            hw = resolved["hardware_id"]
            username = resolved.get("username") or ""

            async with self.db_pool.acquire() as conn:
                snaps = await conn.fetch(
                    """
                    SELECT id, d1_valence, d2_arousal, d3_relational,
                           d4_temporal_depth, d5_integration, coherence,
                           trigger_source, computed_at
                    FROM pgsd_snapshots
                    WHERE user_id = $1
                    ORDER BY computed_at DESC
                    LIMIT 12
                    """,
                    hw,
                )
                seeds: List[Dict[str, Any]] = []
                if username:
                    try:
                        triggers = await conn.fetch(
                            """
                            SELECT date_type, trigger_date, severity, notes_redacted
                            FROM user_trigger_dates
                            WHERE user_id = $1 AND active = TRUE
                            ORDER BY trigger_date DESC NULLS LAST
                            LIMIT 8
                            """,
                            username,
                        )
                        for tr in triggers:
                            seeds.append(
                                {
                                    "source_tag": "sensitive_bridge_trigger",
                                    "temporal_class": "past",
                                    "meta": {
                                        "date_type": tr.get("date_type"),
                                        "trigger_date": str(tr.get("trigger_date")),
                                        "severity": tr.get("severity"),
                                    },
                                }
                            )
                    except Exception:
                        pass

                for snap in snaps:
                    d4 = snap.get("d4_temporal_depth")
                    src = snap.get("trigger_source") or "snapshot"
                    tclass = _classify_temporal(d4, str(src))
                    depth = abs(float(snap.get("coherence") or 0.5) - 0.5) + 0.25
                    row = await conn.fetchrow(
                        """
                        INSERT INTO pgsd_trauma_wells (
                            user_id, username, temporal_class,
                            d1_valence, d2_arousal, d3_relational,
                            d4_temporal, d5_integration,
                            depth, source_tag, meta_json
                        ) VALUES (
                            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb
                        )
                        RETURNING id
                        """,
                        hw,
                        username or None,
                        tclass,
                        snap.get("d1_valence"),
                        snap.get("d2_arousal"),
                        snap.get("d3_relational"),
                        d4,
                        snap.get("d5_integration"),
                        depth,
                        f"snapshot:{snap.get('id')}",
                        json.dumps({"snapshot_id": snap.get("id")}),
                    )
                    if row:
                        ids.append(int(row["id"]))

                for seed in seeds:
                    row = await conn.fetchrow(
                        """
                        INSERT INTO pgsd_trauma_wells (
                            user_id, username, temporal_class,
                            depth, source_tag, meta_json
                        ) VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                        RETURNING id
                        """,
                        hw,
                        username or None,
                        seed["temporal_class"],
                        0.6,
                        seed["source_tag"],
                        json.dumps(seed.get("meta") or {}),
                    )
                    if row:
                        ids.append(int(row["id"]))
            return ids
        except Exception as e:
            logger.debug("TraumaWellEngine.refresh_wells failed: %s", e)
            return ids

    async def collapse_well(self, well_id: int) -> bool:
        """Mark well collapsed. Never raises."""
        try:
            if not field_enabled() or not self.db_pool or not well_id:
                return False
            async with self.db_pool.acquire() as conn:
                result = await conn.execute(
                    """
                    UPDATE pgsd_trauma_wells
                    SET collapsed = TRUE, updated_at = NOW()
                    WHERE id = $1 AND collapsed = FALSE
                    """,
                    int(well_id),
                )
                return result.endswith("1")
        except Exception as e:
            logger.debug("TraumaWellEngine.collapse_well failed: %s", e)
            return False

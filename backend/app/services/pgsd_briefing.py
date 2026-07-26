"""
Compact PGSD field briefing for coach/admin surfaces.  # QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _access_on() -> bool:
    return _env_true("PGSD_ENABLED") and _env_true("ENABLE_PGSD_ACCESS")


def _field_on() -> bool:
    return _env_true("PGSD_ENABLED") and _env_true("ENABLE_PGSD_FIELD")


async def build_field_briefing(
    db_pool: Any,
    raw_id: str,
    max_chars: int = 400,
) -> str:
    """
    One-line-ish briefing from latest snapshot + discernment + wells.
    Returns empty string when disabled or no data. Never raises.
    """
    try:
        if not _access_on() and not _field_on():
            return ""
        if db_pool is None or not raw_id:
            return ""

        from app.services.pgsd_engine import PGSDEngine

        eng = PGSDEngine(db_pool=db_pool)
        resolved = await eng.resolve_pgsd_subject(raw_id)
        if not resolved:
            return ""
        hw = resolved["hardware_id"]
        username = resolved.get("username") or ""

        parts = []
        async with db_pool.acquire() as conn:
            snap = await conn.fetchrow(
                """
                SELECT coherence, d4_temporal_depth, session_region, computed_at
                FROM pgsd_snapshots
                WHERE user_id = $1
                ORDER BY computed_at DESC
                LIMIT 1
                """,
                hw,
            )
            if snap:
                parts.append(
                    "PGSD coh={coh:.2f} d4={d4:.2f} region={reg}".format(
                        coh=float(snap.get("coherence") or 0.0),
                        d4=float(snap.get("d4_temporal_depth") or 0.0),
                        reg=snap.get("session_region") or "—",
                    )
                )

            if _access_on():
                disc = await conn.fetchrow(
                    """
                    SELECT score_composite, score_past, score_present, score_future
                    FROM pgsd_discernment_scores
                    WHERE user_id = $1
                    ORDER BY computed_at DESC
                    LIMIT 1
                    """,
                    hw,
                )
                if disc:
                    parts.append(
                        "discern P/Pt/F={p:.2f}/{pr:.2f}/{f:.2f} Σ={c:.2f}".format(
                            p=float(disc.get("score_past") or 0.0),
                            pr=float(disc.get("score_present") or 0.0),
                            f=float(disc.get("score_future") or 0.0),
                            c=float(disc.get("score_composite") or 0.0),
                        )
                    )

            if _field_on():
                wells = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM pgsd_trauma_wells
                    WHERE user_id = $1 AND collapsed = FALSE
                    """,
                    hw,
                )
                ground = await conn.fetchrow(
                    """
                    SELECT ground_energy, relocation
                    FROM pgsd_ground_states
                    WHERE user_id = $1
                    ORDER BY computed_at DESC
                    LIMIT 1
                    """,
                    hw,
                )
                if wells is not None:
                    parts.append(f"wells={int(wells)} active")
                if ground:
                    parts.append(
                        "ground E={e:.3f} Δ={d:.3f}".format(
                            e=float(ground.get("ground_energy") or 0.0),
                            d=float(ground.get("relocation") or 0.0),
                        )
                    )

        if not parts:
            return ""
        text = " | ".join(parts)
        if username:
            text = f"[{username}] " + text
        return text[: max(0, int(max_chars))]
    except Exception as e:
        logger.debug("build_field_briefing failed (non-fatal): %s", e)
        return ""

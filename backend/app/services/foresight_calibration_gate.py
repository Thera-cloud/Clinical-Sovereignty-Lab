"""
L3c — foresight injection gated by calibration quality.

When resolved foresight predictions are poorly calibrated, soft forward-reasoning
constraints are withheld. Hard safety-adjacent constraint types still pass.

# QUANTUM-CRYSTAL-ARCH — L3 foresight calibration gate
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger("foresight_calibration_gate")

_HARD_TYPES = frozenset({"witness_not_advise", "reduce_intensity", "hold_space"})


def calibration_gate_enabled() -> bool:
    return os.getenv("ENABLE_FORESIGHT_CALIBRATION_GATE", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )


async def foresight_calibration_ok(db_pool: Any) -> bool:
    """True → allow full forward-reasoning injection."""
    if not calibration_gate_enabled() or not db_pool:
        return True
    min_n = int(os.getenv("FORESIGHT_CALIBRATION_MIN_N", "5"))
    max_gap = float(os.getenv("FORESIGHT_CALIBRATION_MAX", "0.35"))
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT accuracy_score, confidence
                FROM foresight_alerts
                WHERE resolved_at IS NOT NULL
                  AND accuracy_score IS NOT NULL
                  AND confidence IS NOT NULL
                ORDER BY resolved_at DESC
                LIMIT 50
                """
            )
        if len(rows) < min_n:
            return True  # insufficient data — do not block
        acc = [float(r["accuracy_score"]) for r in rows]
        conf = [float(r["confidence"]) for r in rows]
        mean_acc = sum(acc) / len(acc)
        mean_conf = sum(conf) / len(conf)
        gap = abs(mean_acc - mean_conf)
        ok = gap <= max_gap
        if not ok:
            logger.info(
                "foresight calibration gate: withholding soft constraints "
                "(gap=%.3f max=%.3f n=%d)",
                gap,
                max_gap,
                len(rows),
            )
        return ok
    except Exception as e:
        logger.debug("foresight_calibration_ok skipped: %s", e)
        return True


def filter_constraints_for_calibration(
    constraints: List[Dict[str, Any]],
    *,
    calibration_ok: bool,
) -> List[Dict[str, Any]]:
    if calibration_ok or not constraints:
        return constraints
    return [c for c in constraints if (c.get("type") or "") in _HARD_TYPES]

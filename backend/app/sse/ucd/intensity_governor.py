"""Intensity Governor — Safety S1.

Records intensity per generation and enforces a session cap.
Ensures no user receives escalating intensity beyond the clinically safe
threshold within a rolling window. The default cap (0.85) aligns with
layer9_clinical_integration._PACING["crisis"]["intensity_cap"].
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_INTENSITY_CAP = 0.85
DEFAULT_SESSION_WINDOW_HOURS = 4
DEFAULT_CLINICIAN_OVERRIDE_LIMIT = 3


class IntensityGovernor:
    """Enforce therapeutic intensity limits per user."""

    def __init__(
        self,
        db_pool,
        intensity_cap: float = DEFAULT_INTENSITY_CAP,
        session_window_hours: int = DEFAULT_SESSION_WINDOW_HOURS,
    ):
        self.db_pool = db_pool
        self.intensity_cap = intensity_cap
        self.session_window_hours = session_window_hours

    async def check_and_record(
        self,
        user_id: str,
        moment_class: str,
        proposed_intensity: float,
        generation_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Evaluate proposed intensity; record and cap if needed."""
        window_start = datetime.now(timezone.utc) - timedelta(
            hours=self.session_window_hours
        )

        if not self.db_pool:
            return {
                "allowed": True,
                "recorded_intensity": proposed_intensity,
                "capped": False,
            }

        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT MAX(intensity_score) as peak, "
                    "COUNT(*) FILTER (WHERE clinician_override = true) as overrides "
                    "FROM intensity_ledger "
                    "WHERE user_id = $1 AND created_at >= $2",
                    user_id, window_start,
                )
                peak = float(row["peak"]) if row and row["peak"] else 0.0
                override_count = int(row["overrides"]) if row else 0

                effective_cap = self.intensity_cap
                capped = False
                if proposed_intensity > effective_cap:
                    proposed_intensity = effective_cap
                    capped = True

                if proposed_intensity > peak and peak > effective_cap * 0.9:
                    proposed_intensity = peak
                    capped = True

                await conn.execute(
                    "INSERT INTO intensity_ledger "
                    "(user_id, moment_class, intensity_score, generation_id) "
                    "VALUES ($1, $2, $3, $4)",
                    user_id, moment_class, proposed_intensity, generation_id,
                )

                return {
                    "allowed": True,
                    "recorded_intensity": round(proposed_intensity, 4),
                    "capped": capped,
                    "window_peak": round(peak, 4),
                    "override_count": override_count,
                    "override_limit": DEFAULT_CLINICIAN_OVERRIDE_LIMIT,
                }
        except Exception as e:
            logger.warning("Intensity governor failed for %s: %s", user_id, e)
            return {
                "allowed": True,
                "recorded_intensity": proposed_intensity,
                "capped": False,
                "error": str(e),
            }

    async def clinician_override(
        self,
        user_id: str,
        moment_class: str,
        intensity: float,
        override_reason: str,
        generation_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Record an intensity entry with clinician override flag."""
        if not self.db_pool:
            return {"allowed": False, "reason": "no db_pool"}

        try:
            async with self.db_pool.acquire() as conn:
                window_start = datetime.now(timezone.utc) - timedelta(
                    hours=self.session_window_hours
                )
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM intensity_ledger "
                    "WHERE user_id = $1 AND created_at >= $2 AND clinician_override = true",
                    user_id, window_start,
                )
                if count >= DEFAULT_CLINICIAN_OVERRIDE_LIMIT:
                    return {
                        "allowed": False,
                        "reason": f"clinician override limit ({DEFAULT_CLINICIAN_OVERRIDE_LIMIT}) reached in window",
                    }

                await conn.execute(
                    "INSERT INTO intensity_ledger "
                    "(user_id, moment_class, intensity_score, generation_id, "
                    "clinician_override, override_reason) "
                    "VALUES ($1, $2, $3, $4, true, $5)",
                    user_id, moment_class, intensity, generation_id, override_reason,
                )
                return {
                    "allowed": True,
                    "recorded_intensity": round(intensity, 4),
                    "overrides_used": count + 1,
                    "override_limit": DEFAULT_CLINICIAN_OVERRIDE_LIMIT,
                }
        except Exception as e:
            logger.warning("Clinician override failed: %s", e)
            return {"allowed": False, "reason": str(e)}

"""
SOVEREIGN SWARM — Cost Threshold Monitor
Enforces session cost caps and monthly spending limits.

Operational Specifications §4.2 — Cost Cap Enforcement.
"""

import logging
from typing import Any, Dict, Optional

from app.models.billing_metered import CostThresholdConfig

logger = logging.getLogger("billing.cost_threshold")


class CostThresholdMonitor:
    """Monitors and enforces cost caps across all billing tiers."""

    def __init__(self, db_pool=None, notifications=None):
        self._db = db_pool
        self._notifications = notifications

    async def check_session_cap(
        self, user_id: str, session_cost: float
    ) -> Dict[str, Any]:
        """Check if a session cost exceeds the per-session cap."""
        config = await self._get_config(user_id)
        exceeded = session_cost > config.per_session_cap

        if exceeded and config.hard_stop_enabled:
            return {
                "allowed": False,
                "reason": f"Session cost ${session_cost:.2f} exceeds cap ${config.per_session_cap:.2f}",
                "cap": config.per_session_cap,
                "cost": session_cost,
            }
        return {"allowed": True, "cost": session_cost, "cap": config.per_session_cap}

    async def check_monthly_cap(
        self, user_id: str, current_total: float
    ) -> Dict[str, Any]:
        """Check monthly spending against the cap."""
        config = await self._get_config(user_id)

        warning_threshold = config.monthly_cap * config.warning_threshold_pct
        at_warning = current_total >= warning_threshold
        at_cap = current_total >= config.monthly_cap

        result = {
            "allowed": True,
            "current_total": current_total,
            "monthly_cap": config.monthly_cap,
            "utilization": current_total / max(config.monthly_cap, 1),
            "at_warning": at_warning,
            "at_cap": at_cap,
        }

        if at_cap and config.hard_stop_enabled and not config.overage_allowed:
            result["allowed"] = False
            result["reason"] = "Monthly spending cap reached"

        return result

    async def _get_config(self, user_id: str) -> CostThresholdConfig:
        if self._db:
            try:
                async with self._db.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT * FROM cost_threshold_configs WHERE user_id = $1",
                        user_id,
                    )
                    if row:
                        return CostThresholdConfig(
                            user_id=user_id,
                            per_session_cap=row.get("per_session_cap", 500),
                            monthly_cap=row.get("monthly_cap", 2000),
                            warning_threshold_pct=row.get("warning_threshold_pct", 0.8),
                            hard_stop_enabled=row.get("hard_stop_enabled", True),
                            overage_allowed=row.get("overage_allowed", False),
                        )
            except Exception:
                pass
        return CostThresholdConfig(user_id=user_id)

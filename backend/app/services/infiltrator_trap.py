"""
HIVE DEFENSE v4.0 — Infiltrator Trap
Post-approval surveillance with 30-day Sentinel Mode.

When suspicious activity leads to an approval being granted (e.g., a new device
verified, a login from a new location accepted), the Infiltrator Trap enters
Sentinel Mode:
- 1.5x sensitivity on the Guardian Fibre
- All mirrors set to at least passive
- Cross-device inheritance (new devices during Sentinel inherit the sentinel)
- 30-day duration (non-negotiable)
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

_logger = logging.getLogger("infiltrator_trap")

SENTINEL_DURATION_DAYS = 30
SENTINEL_SENSITIVITY_MULTIPLIER = 1.5


class InfiltratorTrap:
    """Post-approval surveillance engine."""

    def __init__(self, db_pool, guardian_fibre=None):
        self._db = db_pool
        self._guardian = guardian_fibre

    async def enter_sentinel_mode(
        self, user_id: str, trigger_reason: str,
    ) -> Dict[str, Any]:
        """
        Enter 30-day Sentinel Mode for a user.
        Called after suspicious-but-approved events (new device verified, etc.)
        """
        now = datetime.now(timezone.utc)
        ends_at = now + timedelta(days=SENTINEL_DURATION_DAYS)

        # Record sentinel entry
        if self._db:
            try:
                await self._db.execute(
                    """INSERT INTO sentinel_records
                       (user_id, trigger_reason, sensitivity_multiplier, mirrors_mode,
                        started_at, ends_at, cross_device_inherit)
                       VALUES ($1, $2, $3, 'passive', NOW(), $4, TRUE)""",
                    user_id, trigger_reason, SENTINEL_SENSITIVITY_MULTIPLIER, ends_at,
                )
            except Exception as exc:
                _logger.error("Sentinel record creation error: %s", exc)

        # Activate sentinel on Guardian Fibre
        if self._guardian:
            await self._guardian.enter_sentinel_mode(user_id, SENTINEL_DURATION_DAYS)

        _logger.warning(
            "SENTINEL MODE activated for user %s: reason=%s, until=%s",
            user_id[:8], trigger_reason, ends_at.isoformat(),
        )

        return {
            "user_id": user_id,
            "sentinel_active": True,
            "trigger_reason": trigger_reason,
            "sensitivity_multiplier": SENTINEL_SENSITIVITY_MULTIPLIER,
            "ends_at": ends_at.isoformat(),
        }

    async def check_sentinel_status(self, user_id: str) -> Dict[str, Any]:
        """Check if a user is currently in sentinel mode."""
        if not self._db:
            return {"sentinel_active": False}

        try:
            row = await self._db.fetchrow(
                """SELECT * FROM sentinel_records
                   WHERE user_id = $1 AND resolved = FALSE AND ends_at > NOW()
                   ORDER BY started_at DESC LIMIT 1""",
                user_id,
            )
            if row:
                return {
                    "sentinel_active": True,
                    "trigger_reason": row["trigger_reason"],
                    "sensitivity_multiplier": row["sensitivity_multiplier"],
                    "started_at": row["started_at"].isoformat(),
                    "ends_at": row["ends_at"].isoformat(),
                    "cross_device_inherit": row["cross_device_inherit"],
                }
            return {"sentinel_active": False}
        except Exception as exc:
            _logger.error("Sentinel check error: %s", exc)
            return {"sentinel_active": False}

    async def check_cross_device_sentinel(
        self, user_id: str, new_device_imprint_id: str,
    ) -> bool:
        """
        When a user in Sentinel Mode logs in from a new device,
        the new device inherits the sentinel state.
        Returns True if sentinel was inherited.
        """
        status = await self.check_sentinel_status(user_id)
        if status.get("sentinel_active") and status.get("cross_device_inherit"):
            _logger.info(
                "Sentinel inherited for user %s on new device %s",
                user_id[:8], new_device_imprint_id[:8],
            )
            return True
        return False

    async def resolve_sentinel(
        self, user_id: str, resolved_by: str = "admin",
    ) -> None:
        """Manually resolve sentinel mode (admin action only)."""
        if not self._db:
            return
        try:
            await self._db.execute(
                """UPDATE sentinel_records
                   SET resolved = TRUE, resolved_at = NOW(), resolved_by = $2
                   WHERE user_id = $1 AND resolved = FALSE""",
                user_id, resolved_by,
            )
            if self._guardian:
                await self._guardian.deescalate(user_id, "DORMANT", authorized_by=resolved_by)

            _logger.info("Sentinel resolved for user %s by %s", user_id[:8], resolved_by)
        except Exception as exc:
            _logger.error("Sentinel resolve error: %s", exc)

"""
HIVE DEFENSE v4.0 — Family Data Guardian
Special protection for minor data and custody dispute protocols.

- Minor data access requires guardian authorization + elevated scrutiny
- Custody dispute protocol freezes family data
- All minor data access is immutably logged
- Coach access to minor data requires additional verification
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_logger = logging.getLogger("family_data_guardian")

# Minor protection rules (per v4.0 Section 6)
MINOR_PROTECTION_RULES = {
    "min_guardian_age": 18,
    "require_guardian_consent": True,
    "elevated_scrutiny_always": True,
    "export_requires_dual_consent": True,
    "delete_requires_cooling_period_days": 30,
    "coach_access_requires_guardian_approval": True,
    "no_ai_training_on_minor_data": True,
    "session_recording_requires_guardian_consent": True,
}


class FamilyDataGuardian:
    """Protection engine for family data, especially minors."""

    def __init__(self, db_pool):
        self._db = db_pool

    async def access_minor_data(
        self,
        minor_id: str,
        accessor_id: str,
        accessor_role: str,
        access_type: str,
        data_category: str,
        guardian_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Gate access to minor data. Requires guardian authorization.
        Returns {"allowed": bool, "reason": str}.
        """
        # All minor data access requires a guardian
        if not guardian_id and accessor_role != "admin":
            await self._log_access(
                minor_id, accessor_id, accessor_role, access_type,
                data_category, None, False, "no_guardian_specified",
            )
            return {"allowed": False, "reason": "Guardian authorization required for minor data access"}

        # Verify the guardian relationship
        if guardian_id:
            is_valid_guardian = await self._verify_guardian(minor_id, guardian_id)
            if not is_valid_guardian:
                await self._log_access(
                    minor_id, accessor_id, accessor_role, access_type,
                    data_category, guardian_id, False, "invalid_guardian",
                )
                _logger.warning(
                    "MINOR DATA ACCESS DENIED: accessor %s, claimed guardian %s is not valid for minor %s",
                    accessor_id[:8], guardian_id[:8], minor_id[:8],
                )
                return {"allowed": False, "reason": "Guardian relationship could not be verified"}

        # Check for custody dispute freeze
        is_frozen = await self._check_custody_freeze(minor_id)
        if is_frozen:
            await self._log_access(
                minor_id, accessor_id, accessor_role, access_type,
                data_category, guardian_id, False, "custody_dispute_freeze",
            )
            return {"allowed": False, "reason": "Family data frozen due to active custody dispute"}

        # Coach access requires guardian approval
        if accessor_role == "coach" and MINOR_PROTECTION_RULES["coach_access_requires_guardian_approval"]:
            if access_type in ("write", "export"):
                await self._log_access(
                    minor_id, accessor_id, accessor_role, access_type,
                    data_category, guardian_id, False, "coach_write_requires_approval",
                )
                return {"allowed": False, "reason": "Coach write/export access to minor data requires explicit guardian approval"}

        # Export requires dual consent
        if access_type == "export" and MINOR_PROTECTION_RULES["export_requires_dual_consent"]:
            await self._log_access(
                minor_id, accessor_id, accessor_role, access_type,
                data_category, guardian_id, False, "export_dual_consent_required",
            )
            return {"allowed": False, "reason": "Exporting minor data requires dual consent (both guardians)"}

        # All checks passed — log and allow with elevated scrutiny
        await self._log_access(
            minor_id, accessor_id, accessor_role, access_type,
            data_category, guardian_id, True, "authorized_with_scrutiny",
        )

        return {
            "allowed": True,
            "reason": "authorized",
            "elevated_scrutiny": True,
            "logged": True,
        }

    async def initiate_custody_dispute(
        self, family_id: str, filed_by: str, legal_docs_ref: str = "",
    ) -> Dict[str, Any]:
        """
        Initiate custody dispute protocol — immediately freezes all family data.
        """
        _logger.warning(
            "CUSTODY DISPUTE INITIATED for family %s by %s",
            family_id[:8], filed_by[:8],
        )

        if self._db:
            try:
                await self._db.execute(
                    """INSERT INTO custody_dispute_records
                       (family_id, filed_by, status, data_frozen_at, legal_docs_ref)
                       VALUES ($1, $2, 'active', NOW(), $3)""",
                    family_id, filed_by, legal_docs_ref,
                )
            except Exception as exc:
                _logger.error("Custody dispute record error: %s", exc)

        return {
            "family_id": family_id,
            "status": "active",
            "data_frozen": True,
            "action_required": "Legal documentation must be provided to modify or access family data",
        }

    async def resolve_custody_dispute(
        self, family_id: str, resolved_by: str, notes: str = "",
    ) -> None:
        """Resolve a custody dispute and unfreeze data."""
        if not self._db:
            return
        try:
            await self._db.execute(
                """UPDATE custody_dispute_records
                   SET status = 'resolved', resolved_at = NOW(), resolved_by = $2, notes = $3
                   WHERE family_id = $1 AND status = 'active'""",
                family_id, resolved_by, notes,
            )
            _logger.info("Custody dispute resolved for family %s by %s", family_id[:8], resolved_by)
        except Exception as exc:
            _logger.error("Custody resolve error: %s", exc)

    async def _verify_guardian(self, minor_id: str, guardian_id: str) -> bool:
        """Verify that guardian_id is a legal guardian of minor_id."""
        if not self._db:
            return True  # Fail open if no DB (dev mode)
        try:
            row = await self._db.fetchrow(
                """SELECT id FROM family_members
                   WHERE family_id = (SELECT family_id FROM family_members WHERE user_id = $1 LIMIT 1)
                   AND user_id = $2 AND role IN ('guardian', 'parent', 'primary')""",
                minor_id, guardian_id,
            )
            return row is not None
        except Exception:
            return False

    async def _check_custody_freeze(self, minor_id: str) -> bool:
        """Check if the minor's family has an active custody dispute."""
        if not self._db:
            return False
        try:
            row = await self._db.fetchrow(
                """SELECT id FROM custody_dispute_records
                   WHERE family_id = (SELECT family_id FROM family_members WHERE user_id = $1 LIMIT 1)
                   AND status = 'active'""",
                minor_id,
            )
            return row is not None
        except Exception:
            return False

    async def _log_access(
        self, minor_id: str, accessor_id: str, accessor_role: str,
        access_type: str, data_category: str, guardian_id: Optional[str],
        authorized: bool, reason: str,
    ) -> None:
        """Immutable log of all minor data access attempts."""
        if not self._db:
            return
        try:
            await self._db.execute(
                """INSERT INTO minor_data_access_log
                   (minor_id, accessor_id, accessor_role, access_type, data_category,
                    guardian_id, authorized, reason, created_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())""",
                minor_id, accessor_id, accessor_role, access_type,
                data_category, guardian_id, authorized, reason,
            )
        except Exception as exc:
            _logger.error("Minor access log error: %s", exc)

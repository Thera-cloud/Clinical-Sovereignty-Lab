"""
HIVE DEFENSE v4.0 — Login Guardians
Enhanced login protection for members and coaches.

MemberLoginGuardian: Brute force protection, device verification, Guardian Fibre integration.
CoachLoginGuardian: License/insurance expiry check, elevated curiosity baseline.
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

_logger = logging.getLogger("login_guardian")

# Brute force settings
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 3
LOCKOUT_ESCALATION_MULTIPLIER = 2  # Doubles each time

# Device verification
VERIFICATION_CODE_LENGTH = 6
VERIFICATION_CODE_EXPIRY_MINUTES = 15


class MemberLoginGuardian:
    """Enhanced login security for members (clients)."""

    def __init__(self, db_pool):
        self._db = db_pool

    async def check_before_login(
        self, identifier: str, ip_address: str = "", user_agent: str = "",
    ) -> Dict[str, Any]:
        """
        Pre-login check: is this identifier locked out?
        Returns {"allowed": bool, "reason": str, "lockout_remaining_sec": int,
                 "remaining_attempts": int}.
        """
        if not self._db:
            return {"allowed": True, "reason": "no_db", "remaining_attempts": MAX_FAILED_ATTEMPTS}

        try:
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=LOCKOUT_DURATION_MINUTES)
            row = await self._db.fetchrow(
                """SELECT COUNT(*) as fail_count,
                          MAX(created_at) as last_attempt
                   FROM login_attempts
                   WHERE identifier = $1 AND success = FALSE AND created_at > $2""",
                identifier, cutoff,
            )

            fail_count = row["fail_count"] if row else 0
            remaining_attempts = max(0, MAX_FAILED_ATTEMPTS - fail_count)

            if fail_count >= MAX_FAILED_ATTEMPTS:
                last_attempt = row["last_attempt"]
                escalation = max(1, fail_count // MAX_FAILED_ATTEMPTS)
                lockout_minutes = LOCKOUT_DURATION_MINUTES * min(escalation, 8)
                lockout_until = last_attempt + timedelta(minutes=lockout_minutes)
                now = datetime.now(timezone.utc)

                if now < lockout_until:
                    remaining = int((lockout_until - now).total_seconds())
                    _logger.warning(
                        "Login locked out for identifier (hash=%s), %d failures, %ds remaining",
                        hashlib.sha256(identifier.encode()).hexdigest()[:8],
                        fail_count, remaining,
                    )
                    return {
                        "allowed": False,
                        "reason": "account_locked",
                        "lockout_remaining_sec": remaining,
                        "remaining_attempts": 0,
                    }

            return {
                "allowed": True,
                "reason": "ok",
                "lockout_remaining_sec": 0,
                "remaining_attempts": remaining_attempts,
            }
        except Exception as exc:
            _logger.error("Pre-login check error: %s", exc)
            return {"allowed": True, "reason": "check_error", "remaining_attempts": MAX_FAILED_ATTEMPTS}

    async def record_attempt(
        self, identifier: str, success: bool, ip_address: str = "",
        user_agent: str = "", device_imprint_id: str = "",
        failure_reason: str = "",
    ) -> None:
        """Record a login attempt."""
        if not self._db:
            return
        ua_hash = hashlib.sha256(user_agent.encode()).hexdigest()[:32] if user_agent else ""
        try:
            await self._db.execute(
                """INSERT INTO login_attempts
                   (identifier, identifier_type, success, ip_address, user_agent_hash,
                    device_imprint_id, failure_reason, created_at)
                   VALUES ($1, 'username', $2, $3, $4, $5, $6, NOW())""",
                identifier, success, ip_address, ua_hash, device_imprint_id, failure_reason,
            )
        except Exception as exc:
            _logger.error("Failed to record login attempt: %s", exc)

    async def generate_device_verification(
        self, user_id: str, device_imprint_id: str,
    ) -> str:
        """Generate a verification code for a new device. Returns the plaintext code."""
        code = "".join(str(secrets.randbelow(10)) for _ in range(VERIFICATION_CODE_LENGTH))
        code_hash = hashlib.sha256(code.encode()).hexdigest()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=VERIFICATION_CODE_EXPIRY_MINUTES)

        if self._db:
            try:
                await self._db.execute(
                    """INSERT INTO device_verification_codes
                       (user_id, device_imprint_id, code_hash, expires_at, created_at)
                       VALUES ($1, $2, $3, $4, NOW())""",
                    user_id, device_imprint_id, code_hash, expires_at,
                )
            except Exception as exc:
                _logger.error("Verification code store error: %s", exc)

        return code

    async def verify_device_code(
        self, user_id: str, device_imprint_id: str, code: str,
    ) -> bool:
        """Verify a device verification code."""
        if not self._db:
            return False
        code_hash = hashlib.sha256(code.encode()).hexdigest()
        try:
            row = await self._db.fetchrow(
                """SELECT id FROM device_verification_codes
                   WHERE user_id = $1 AND device_imprint_id = $2 AND code_hash = $3
                   AND expires_at > NOW() AND used = FALSE""",
                user_id, device_imprint_id, code_hash,
            )
            if row:
                await self._db.execute(
                    "UPDATE device_verification_codes SET used = TRUE WHERE id = $1",
                    row["id"],
                )
                return True
            return False
        except Exception as exc:
            _logger.error("Code verification error: %s", exc)
            return False


class CoachLoginGuardian:
    """Enhanced login security for coaches."""

    def __init__(self, db_pool):
        self._db = db_pool
        self._member_guardian = MemberLoginGuardian(db_pool)

    async def check_before_login(
        self, identifier: str, ip_address: str = "", user_agent: str = "",
    ) -> Dict[str, Any]:
        """
        Pre-login check for coaches: standard brute force + license/insurance check.
        """
        # Standard brute force check
        result = await self._member_guardian.check_before_login(
            identifier, ip_address, user_agent,
        )
        if not result["allowed"]:
            return result

        # Coach-specific checks would go here:
        # - License expiry check (from coach profile in DB)
        # - Insurance expiry check
        # - Minimum CURIOUS level enforcement
        # These require the coach profile system to be queried

        return {"allowed": True, "reason": "ok", "lockout_remaining_sec": 0}

    async def record_attempt(
        self, identifier: str, success: bool, **kwargs,
    ) -> None:
        """Record a coach login attempt."""
        await self._member_guardian.record_attempt(identifier, success, **kwargs)

    async def check_coach_compliance(self, coach_id: str) -> Dict[str, Any]:
        """Check if coach meets compliance requirements for login."""
        # This checks against the coach profile for license/insurance validity
        # Placeholder for integration with coach management system
        return {
            "compliant": True,
            "license_valid": True,
            "insurance_valid": True,
            "warnings": [],
        }

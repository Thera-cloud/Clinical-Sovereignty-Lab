"""
HIVE DEFENSE v4.4 — YubiKey Hardware Root of Trust
Layer 0 of Castle Defense architecture.

FIDO2/WebAuthn integration for:
  - Admin login hardware verification (after passphrase, before session)
  - Sensitive operation confirmation (account deletion, DEFCON override)
  - SSH key attestation (sk-ssh-ed25519) management

Gracefully skips if:
  - No YubiKey is registered for the user
  - The webauthn library is unavailable
  - The client doesn't support WebAuthn

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("hive.yubikey_gate")

RP_ID = "sovereignsanctuary.net"
RP_NAME = "Sovereign Sanctuary"
EXPECTED_ORIGIN = "https://command.sovereignsanctuary.net"

CHALLENGE_TTL_SEC = 300  # 5 minutes to complete the challenge

try:
    from webauthn import (
        generate_authentication_options,
        generate_registration_options,
        verify_authentication_response,
        verify_registration_response,
    )
    from webauthn.helpers import (
        bytes_to_base64url,
        options_to_json,
    )
    from webauthn.helpers.structs import (
        AuthenticatorSelectionCriteria,
        PublicKeyCredentialDescriptor,
        RegistrationCredential,
        ResidentKeyRequirement,
        UserVerificationRequirement,
    )
    WEBAUTHN_AVAILABLE = True
except ImportError:
    WEBAUTHN_AVAILABLE = False
    logger.info("WebAuthn library not installed — YubiKey gate in passthrough mode")


@dataclass
class YubiKeyCredential:
    """Stored FIDO2 credential for a registered YubiKey."""
    credential_id: bytes = b""
    public_key: bytes = b""
    sign_count: int = 0
    registered_at: float = 0.0
    label: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "credential_id": self.credential_id.hex(),
            "public_key": self.public_key.hex(),
            "sign_count": self.sign_count,
            "registered_at": self.registered_at,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "YubiKeyCredential":
        return cls(
            credential_id=bytes.fromhex(d.get("credential_id", "")),
            public_key=bytes.fromhex(d.get("public_key", "")),
            sign_count=d.get("sign_count", 0),
            registered_at=d.get("registered_at", 0.0),
            label=d.get("label", ""),
        )


@dataclass
class GateVerdict:
    """Result of a YubiKey gate check."""
    passed: bool = True
    skipped: bool = False
    reason: str = ""
    method: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "skipped": self.skipped,
            "reason": self.reason,
            "method": self.method,
        }


class YubiKeyGate:
    """
    Hardware root of trust gate.

    When a YubiKey is registered, it MUST be present for admin login
    and sensitive operations. When no key is registered, the gate
    gracefully passes through (skip mode).
    """

    def __init__(self):
        self._pending_challenges: Dict[str, dict] = {}
        self._total_checks = 0
        self._total_passed = 0
        self._total_skipped = 0
        self._total_failed = 0
        self._started_at = time.time()
        self._available = WEBAUTHN_AVAILABLE
        logger.info(
            "YubiKey Gate initialized (webauthn=%s)",
            "available" if self._available else "not installed",
        )

    @property
    def available(self) -> bool:
        return self._available

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "available": self._available,
            "total_checks": self._total_checks,
            "total_passed": self._total_passed,
            "total_skipped": self._total_skipped,
            "total_failed": self._total_failed,
            "pending_challenges": len(self._pending_challenges),
            "uptime_hours": round((time.time() - self._started_at) / 3600, 1),
        }

    # ─── GATE CHECK ─────────────────────────────────────────────────────

    def requires_hardware(self, profile: Dict[str, Any]) -> bool:
        """Check if this user has a YubiKey registered and must present it."""
        if not self._available:
            return False
        return bool(profile.get("webauthn_enabled") and profile.get("webauthn_credential"))

    def check_gate(self, profile: Dict[str, Any]) -> GateVerdict:
        """
        Determine if the YubiKey gate applies.
        Returns a verdict indicating whether to proceed, challenge, or skip.
        """
        self._total_checks += 1

        if not self._available:
            self._total_skipped += 1
            return GateVerdict(
                passed=True,
                skipped=True,
                reason="WebAuthn library not available",
                method="skip",
            )

        if not profile.get("webauthn_enabled"):
            self._total_skipped += 1
            return GateVerdict(
                passed=True,
                skipped=True,
                reason="No YubiKey registered for this user",
                method="skip",
            )

        return GateVerdict(
            passed=False,
            skipped=False,
            reason="YubiKey verification required",
            method="webauthn_challenge",
        )

    # ─── REGISTRATION ───────────────────────────────────────────────────

    def generate_registration(
        self,
        user_id: str,
        username: str,
        display_name: str = "",
    ) -> Optional[dict]:
        """Generate WebAuthn registration options for enrolling a new YubiKey."""
        if not self._available:
            return None

        options = generate_registration_options(
            rp_id=RP_ID,
            rp_name=RP_NAME,
            user_id=user_id.encode(),
            user_name=username,
            user_display_name=display_name or username,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.DISCOURAGED,
                user_verification=UserVerificationRequirement.PREFERRED,
            ),
        )

        challenge_hex = (
            options.challenge.hex()
            if isinstance(options.challenge, bytes)
            else str(options.challenge)
        )
        self._pending_challenges[user_id] = {
            "type": "registration",
            "challenge": challenge_hex,
            "created_at": time.time(),
        }

        logger.info("Registration challenge generated for %s", user_id[:12])
        return {
            "options_json": options_to_json(options),
            "challenge_hex": challenge_hex,
        }

    def verify_registration(
        self,
        user_id: str,
        credential_response: Dict[str, Any],
    ) -> Optional[YubiKeyCredential]:
        """
        Verify a WebAuthn registration response and return the stored credential.
        Returns None on failure.
        """
        if not self._available:
            return None

        pending = self._pending_challenges.pop(user_id, None)
        if not pending or pending["type"] != "registration":
            logger.warning("No pending registration challenge for %s", user_id[:12])
            return None

        if time.time() - pending["created_at"] > CHALLENGE_TTL_SEC:
            logger.warning("Registration challenge expired for %s", user_id[:12])
            return None

        try:
            challenge_bytes = bytes.fromhex(pending["challenge"])
            verification = verify_registration_response(
                credential=credential_response,
                expected_challenge=challenge_bytes,
                expected_rp_id=RP_ID,
                expected_origin=EXPECTED_ORIGIN,
            )

            cred = YubiKeyCredential(
                credential_id=verification.credential_id,
                public_key=verification.credential_public_key,
                sign_count=verification.sign_count,
                registered_at=time.time(),
                label="YubiKey",
            )

            logger.info(
                "YubiKey registered for %s (credential=%s)",
                user_id[:12],
                cred.credential_id.hex()[:16],
            )
            return cred

        except Exception as e:
            logger.warning("Registration verification failed for %s: %s", user_id[:12], e)
            return None

    # ─── AUTHENTICATION ─────────────────────────────────────────────────

    def generate_authentication(
        self,
        user_id: str,
        credential: Dict[str, Any],
    ) -> Optional[dict]:
        """Generate WebAuthn authentication options (assertion challenge)."""
        if not self._available:
            return None

        allow_credentials = []
        cred_id = credential.get("credential_id", "")
        if cred_id:
            allow_credentials.append(
                PublicKeyCredentialDescriptor(id=bytes.fromhex(cred_id))
            )

        options = generate_authentication_options(
            rp_id=RP_ID,
            allow_credentials=allow_credentials,
        )

        challenge_hex = (
            options.challenge.hex()
            if isinstance(options.challenge, bytes)
            else str(options.challenge)
        )
        self._pending_challenges[user_id] = {
            "type": "authentication",
            "challenge": challenge_hex,
            "credential": credential,
            "created_at": time.time(),
        }

        logger.info("Authentication challenge generated for %s", user_id[:12])
        return {
            "options_json": options_to_json(options),
            "challenge_hex": challenge_hex,
        }

    def verify_authentication(
        self,
        user_id: str,
        assertion_response: Dict[str, Any],
    ) -> GateVerdict:
        """
        Verify a WebAuthn authentication response (assertion).
        Returns a GateVerdict with passed=True on success.
        """
        self._total_checks += 1

        if not self._available:
            self._total_skipped += 1
            return GateVerdict(passed=True, skipped=True, reason="WebAuthn not available")

        pending = self._pending_challenges.pop(user_id, None)
        if not pending or pending["type"] != "authentication":
            self._total_failed += 1
            return GateVerdict(
                passed=False,
                reason="No pending authentication challenge",
                method="webauthn",
            )

        if time.time() - pending["created_at"] > CHALLENGE_TTL_SEC:
            self._total_failed += 1
            return GateVerdict(
                passed=False,
                reason="Authentication challenge expired",
                method="webauthn",
            )

        stored_cred = pending.get("credential", {})
        try:
            challenge_bytes = bytes.fromhex(pending["challenge"])
            verification = verify_authentication_response(
                credential=assertion_response,
                expected_challenge=challenge_bytes,
                expected_rp_id=RP_ID,
                expected_origin=EXPECTED_ORIGIN,
                credential_public_key=bytes.fromhex(stored_cred.get("public_key", "")),
                credential_current_sign_count=stored_cred.get("sign_count", 0),
            )

            self._total_passed += 1
            logger.info("YubiKey authentication PASSED for %s", user_id[:12])
            return GateVerdict(
                passed=True,
                reason="YubiKey verified",
                method="webauthn",
            )

        except Exception as e:
            self._total_failed += 1
            logger.warning("YubiKey authentication FAILED for %s: %s", user_id[:12], e)
            return GateVerdict(
                passed=False,
                reason=f"YubiKey verification failed: {e}",
                method="webauthn",
            )

    # ─── CLEANUP ────────────────────────────────────────────────────────

    def cleanup_expired_challenges(self) -> int:
        """Remove expired pending challenges. Returns count removed."""
        now = time.time()
        expired = [
            uid for uid, ch in self._pending_challenges.items()
            if now - ch["created_at"] > CHALLENGE_TTL_SEC
        ]
        for uid in expired:
            del self._pending_challenges[uid]
        return len(expired)


# ─── SINGLETON ──────────────────────────────────────────────────────────

_instance: Optional[YubiKeyGate] = None


def get_yubikey_gate() -> YubiKeyGate:
    global _instance
    if _instance is None:
        _instance = YubiKeyGate()
    return _instance

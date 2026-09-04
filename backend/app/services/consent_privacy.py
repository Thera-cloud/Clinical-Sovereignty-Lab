"""
Therapeutic Identity Inference Engine — Phase 7: BIPA Consent & Privacy.

Manages consent flows for voice enrollment and identity inference:
- SMS Magic Link consent (BIPA compliance)
- In-app consent dialogs
- Parental pre-authorization (COPPA/FERPA) for minors
- Vouched Enrollment for institutional settings
- Consent expiry and revocation
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger("nate.consent_privacy")

CONSENT_TYPES = {
    "voice_enrollment": {
        "description": "Permission to store voice characteristics for identity verification",
        "bipa_relevant": True,
        "default_expiry_days": 365,
    },
    "identity_inference": {
        "description": "Permission to use identity inference during calls",
        "bipa_relevant": True,
        "default_expiry_days": 365,
    },
    "data_retention": {
        "description": "Permission to retain session data and transcripts",
        "bipa_relevant": False,
        "default_expiry_days": 365,
    },
    "minor_enrollment": {
        "description": "Parental consent for minor voice enrollment",
        "bipa_relevant": True,
        "default_expiry_days": 180,
    },
}


@dataclass
class ConsentRequest:
    """A pending consent request awaiting user action."""
    request_id: str
    user_id: str
    tenant_id: str
    consent_type: str
    magic_link_hash: str
    phone: Optional[str] = None
    parent_user_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 3600)
    fulfilled: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "consent_type": self.consent_type,
            "fulfilled": self.fulfilled,
            "expires_in_s": max(0, self.expires_at - time.time()),
        }


class ConsentPrivacyManager:
    """
    Manages the full consent lifecycle for voice identity features.

    Consent methods:
    - SMS Magic Link: send a link, user clicks to consent
    - In-App: consent dialog within the Flutter app
    - Parental: parent pre-authorizes minor enrollment (COPPA/FERPA)
    - Vouched: institutional admin vouches for a cohort
    """

    def __init__(self, db_pool=None, twilio_client=None):
        self._db = db_pool
        self._twilio = twilio_client
        self._pending: Dict[str, ConsentRequest] = {}

    async def create_sms_magic_link(
        self,
        user_id: str,
        tenant_id: str,
        consent_type: str,
        phone: str,
    ) -> Optional[ConsentRequest]:
        """
        Generate a magic link and send it via SMS.
        Returns the ConsentRequest if SMS was sent.
        """
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        request = ConsentRequest(
            request_id=secrets.token_hex(16),
            user_id=user_id,
            tenant_id=tenant_id,
            consent_type=consent_type,
            magic_link_hash=token_hash,
            phone=phone,
        )

        consent_info = CONSENT_TYPES.get(consent_type, {})
        description = consent_info.get("description", consent_type)

        base_url = os.getenv("APP_BASE_URL", "https://app.sovereignsanctuary.net")
        link = f"{base_url}/consent?token={token}&type={consent_type}"

        sms_body = (
            f"Sovereign Sanctuary — Consent Request\n\n"
            f"{description}\n\n"
            f"Tap to consent: {link}\n\n"
            f"This link expires in 1 hour. "
            f"If you did not request this, please ignore."
        )

        if self._twilio:
            try:
                from app.services.twilio_a2p import sms_create_kwargs

                msg_kwargs = sms_create_kwargs(phone, sms_body)
                if not msg_kwargs:
                    logger.warning(
                        "ConsentPrivacy: no TWILIO_MESSAGING_SERVICE_SID or from number — SMS not sent"
                    )
                    return None

                self._twilio.messages.create(**msg_kwargs)
                logger.info("ConsentPrivacy: SMS sent to %s for %s", phone[-4:], consent_type)
            except Exception as e:
                logger.warning("ConsentPrivacy: SMS send failed: %s", e)
                return None

        self._pending[request.request_id] = request

        if self._db:
            try:
                await self._db.execute(
                    """INSERT INTO consent_requests
                       (request_id, user_id, tenant_id, consent_type,
                        magic_link_hash, phone, created_at, expires_at, fulfilled)
                       VALUES ($1, $2, $3, $4, $5, $6,
                               to_timestamp($7), to_timestamp($8), false)""",
                    request.request_id, user_id, tenant_id, consent_type,
                    token_hash, phone, request.created_at, request.expires_at,
                )
            except Exception as e:
                logger.warning("ConsentPrivacy: DB store failed: %s", e)

        return request

    async def verify_magic_link(self, token: str) -> Optional[ConsentRequest]:
        """Verify a magic link token and fulfill the consent."""
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        for req in self._pending.values():
            if req.magic_link_hash == token_hash and not req.fulfilled:
                if time.time() > req.expires_at:
                    return None
                req.fulfilled = True
                await self._persist_consent(req)
                return req

        if self._db:
            try:
                row = await self._db.fetchrow(
                    """SELECT * FROM consent_requests
                       WHERE magic_link_hash = $1 AND fulfilled = false
                       AND expires_at > NOW()""",
                    token_hash,
                )
                if row:
                    await self._db.execute(
                        "UPDATE consent_requests SET fulfilled = true WHERE request_id = $1",
                        row["request_id"],
                    )
                    req = ConsentRequest(
                        request_id=row["request_id"],
                        user_id=row["user_id"],
                        tenant_id=row["tenant_id"],
                        consent_type=row["consent_type"],
                        magic_link_hash=token_hash,
                        fulfilled=True,
                    )
                    await self._persist_consent(req)
                    return req
            except Exception as e:
                logger.warning("ConsentPrivacy: verify failed: %s", e)

        return None

    async def create_parental_consent(
        self,
        minor_user_id: str,
        parent_user_id: str,
        tenant_id: str,
        parent_phone: str,
    ) -> Optional[ConsentRequest]:
        """
        Create a parental consent request for a minor (COPPA/FERPA).
        The SMS goes to the parent, not the minor.
        """
        return await self.create_sms_magic_link(
            user_id=minor_user_id,
            tenant_id=tenant_id,
            consent_type="minor_enrollment",
            phone=parent_phone,
        )

    async def vouch_enrollment(
        self,
        admin_user_id: str,
        tenant_id: str,
        user_ids: list,
    ) -> int:
        """
        Institutional admin vouches for a cohort of users.
        Creates consent records for all specified users.
        """
        count = 0
        for uid in user_ids:
            try:
                from .institutional_deployment import ConsentRecord
                record = ConsentRecord(
                    user_id=uid,
                    tenant_id=tenant_id,
                    consent_type="voice_enrollment",
                    granted=True,
                    consent_method="vouched",
                    consent_source=admin_user_id,
                )
                if self._db:
                    await self._db.execute(
                        """INSERT INTO consent_records
                           (user_id, tenant_id, consent_type, granted,
                            consent_method, consent_source, granted_at)
                           VALUES ($1, $2, $3, true, 'vouched', $4, NOW())
                           ON CONFLICT (user_id, tenant_id, consent_type)
                           DO UPDATE SET granted = true, consent_source = $4,
                                         granted_at = NOW()""",
                        uid, tenant_id, "voice_enrollment", admin_user_id,
                    )
                    count += 1
            except Exception as e:
                logger.warning("ConsentPrivacy: vouch failed for %s: %s", uid, e)

        return count

    async def revoke_consent(
        self, user_id: str, tenant_id: str, consent_type: str,
    ) -> bool:
        """Revoke a user's consent and schedule data deletion."""
        if not self._db:
            return False

        try:
            await self._db.execute(
                """UPDATE consent_records
                   SET granted = false, revoked_at = NOW()
                   WHERE user_id = $1 AND tenant_id = $2 AND consent_type = $3""",
                user_id, tenant_id, consent_type,
            )

            if consent_type == "voice_enrollment":
                await self._schedule_voiceprint_deletion(user_id, tenant_id)

            return True
        except Exception as e:
            logger.warning("ConsentPrivacy: revoke failed: %s", e)
            return False

    async def _persist_consent(self, req: ConsentRequest) -> None:
        """Convert a fulfilled request into a consent record."""
        if not self._db:
            return

        consent_info = CONSENT_TYPES.get(req.consent_type, {})
        expiry_days = consent_info.get("default_expiry_days", 365)

        try:
            await self._db.execute(
                """INSERT INTO consent_records
                   (user_id, tenant_id, consent_type, granted,
                    consent_method, granted_at, expires_at)
                   VALUES ($1, $2, $3, true, 'sms_magic_link', NOW(),
                           NOW() + make_interval(days => $4))
                   ON CONFLICT (user_id, tenant_id, consent_type)
                   DO UPDATE SET granted = true, granted_at = NOW(),
                                 expires_at = NOW() + make_interval(days => $4)""",
                req.user_id, req.tenant_id, req.consent_type, expiry_days,
            )
        except Exception as e:
            logger.warning("ConsentPrivacy: persist consent failed: %s", e)

    async def _schedule_voiceprint_deletion(
        self, user_id: str, tenant_id: str,
    ) -> None:
        """Schedule deletion of voice enrollment data after consent revocation."""
        if not self._db:
            return

        try:
            await self._db.execute(
                """INSERT INTO data_deletion_queue
                   (user_id, tenant_id, data_type, scheduled_at, execute_after)
                   VALUES ($1, $2, 'voice_enrollment', NOW(), NOW() + INTERVAL '30 days')
                   ON CONFLICT DO NOTHING""",
                user_id, tenant_id,
            )
        except Exception as e:
            logger.warning("ConsentPrivacy: deletion schedule failed: %s", e)

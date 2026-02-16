"""
Me-2-Me Platinum — Three-Level Consent Management
MUST be the first Me-2-Me service initialized.
Manages observe → preserve → interact consent levels.

Me2Me Platinum Legacy Architecture v1 §1 — Consent Architecture.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.models.me2me import ConsentLevel, ConsentRecord, ConsentStatus
from app.services.me2me.constants import CONSENT_RENEWAL_DAYS, CONSENT_VERSION

logger = logging.getLogger("me2me.consent")


class Me2MeConsentService:
    """
    Manages the three-level consent architecture for Me-2-Me.
    All Me-2-Me operations MUST check consent before proceeding.
    """

    def __init__(self, db_pool=None, notifications=None):
        self._db = db_pool
        self._notifications = notifications
        self._cache: Dict[str, ConsentRecord] = {}

    async def grant_consent(
        self,
        user_id: str,
        level: ConsentLevel,
        witness_signature: Optional[str] = None,
    ) -> ConsentRecord:
        """Grant consent at the specified level.
        
        Consent progression rules:
        - OBSERVE can be granted directly
        - PRESERVE requires existing OBSERVE (or higher)
        - INTERACT requires existing PRESERVE (or higher)
        """
        level_order = {
            ConsentLevel.OBSERVE: 1,
            ConsentLevel.PRESERVE: 2,
            ConsentLevel.INTERACT: 3,
        }

        # Check consent level progression
        if level_order.get(level, 0) > 1:
            existing = await self.get_consent(user_id)
            if existing and existing.status == ConsentStatus.ACTIVE:
                existing_order = level_order.get(existing.level, 0)
                required_order = level_order.get(level, 0) - 1
                if existing_order < required_order:
                    required_level_name = [
                        k.value for k, v in level_order.items() if v == required_order
                    ][0] if required_order > 0 else "observe"
                    logger.warning(
                        "Consent progression violation: user=%s requested=%s requires=%s first",
                        user_id, level.value, required_level_name,
                    )
                    raise ValueError(
                        f"Cannot grant {level.value} consent without {required_level_name} consent first"
                    )
            elif not existing or existing.status != ConsentStatus.ACTIVE:
                if level != ConsentLevel.OBSERVE:
                    logger.warning(
                        "Consent progression violation: user=%s has no active consent, requested=%s",
                        user_id, level.value,
                    )
                    raise ValueError(
                        f"Cannot grant {level.value} consent without observe consent first"
                    )

        record = ConsentRecord(
            user_id=user_id,
            level=level,
            status=ConsentStatus.ACTIVE,
            granted_at=datetime.utcnow(),
            renewal_due=datetime.utcnow() + timedelta(days=CONSENT_RENEWAL_DAYS),
            witness_signature=witness_signature,
            legal_notice_acknowledged=True,
            version=CONSENT_VERSION,
        )

        record.audit_trail.append({
            "action": "consent_granted",
            "level": level.value,
            "timestamp": datetime.utcnow().isoformat(),
            "witness": witness_signature,
        })

        await self._persist_consent(record)
        self._cache[user_id] = record

        logger.info(
            "Me-2-Me consent granted: user=%s level=%s",
            user_id, level.value,
        )
        return record

    async def revoke_consent(self, user_id: str) -> ConsentRecord:
        """Revoke all Me-2-Me consent. Data collection stops immediately."""
        record = await self.get_consent(user_id)
        if not record:
            record = ConsentRecord(
                user_id=user_id,
                level=ConsentLevel.OBSERVE,
                status=ConsentStatus.REVOKED,
            )

        record.status = ConsentStatus.REVOKED
        record.revoked_at = datetime.utcnow()
        record.audit_trail.append({
            "action": "consent_revoked",
            "timestamp": datetime.utcnow().isoformat(),
        })

        await self._persist_consent(record)
        self._cache[user_id] = record

        logger.warning("Me-2-Me consent revoked: user=%s", user_id)
        return record

    async def check_consent(
        self, user_id: str, required_level: ConsentLevel
    ) -> bool:
        """Check if a user has the required consent level."""
        record = await self.get_consent(user_id)
        if not record:
            return False
        if record.status != ConsentStatus.ACTIVE:
            return False

        # Check renewal
        if record.renewal_due and record.renewal_due < datetime.utcnow():
            record.status = ConsentStatus.SUSPENDED
            await self._persist_consent(record)
            return False

        # Level hierarchy: interact > preserve > observe
        level_order = {
            ConsentLevel.OBSERVE: 1,
            ConsentLevel.PRESERVE: 2,
            ConsentLevel.INTERACT: 3,
        }
        return level_order.get(record.level, 0) >= level_order.get(required_level, 0)

    async def get_consent(self, user_id: str) -> Optional[ConsentRecord]:
        """Get the current consent record for a user."""
        if user_id in self._cache:
            return self._cache[user_id]

        if self._db:
            try:
                async with self._db.acquire() as conn:
                    row = await conn.fetchrow(
                        """SELECT * FROM me2me_consent_records
                        WHERE user_id = $1
                        ORDER BY created_at DESC LIMIT 1""",
                        user_id,
                    )
                    if row:
                        record = ConsentRecord(
                            consent_id=row["consent_id"],
                            user_id=user_id,
                            level=ConsentLevel(row["level"]),
                            status=ConsentStatus(row["status"]),
                            granted_at=row.get("granted_at"),
                            revoked_at=row.get("revoked_at"),
                            renewal_due=row.get("renewal_due"),
                            witness_signature=row.get("witness_signature"),
                            version=row.get("version", 1),
                        )
                        self._cache[user_id] = record
                        return record
            except Exception as e:
                logger.error("Consent query failed: %s", e)
        return None

    async def check_renewals(self) -> List[str]:
        """Check for consent records approaching renewal. Returns user IDs needing renewal."""
        needs_renewal = []
        if not self._db:
            return needs_renewal

        try:
            async with self._db.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT user_id FROM me2me_consent_records
                    WHERE status = 'active'
                    AND renewal_due < NOW() + INTERVAL '30 days'"""
                )
                for row in rows:
                    needs_renewal.append(row["user_id"])
                    if self._notifications:
                        await self._notifications.send_notification(
                            user_id=row["user_id"],
                            notification_type="me2me_consent_renewal",
                            title="Me-2-Me Consent Renewal",
                            body="Your Me-2-Me consent is due for renewal. Please review and confirm.",
                            channel="push",
                        )
        except Exception as e:
            logger.error("Renewal check failed: %s", e)

        return needs_renewal

    async def _persist_consent(self, record: ConsentRecord) -> None:
        if not self._db:
            return
        try:
            async with self._db.acquire() as conn:
                await conn.execute(
                    """INSERT INTO me2me_consent_records
                    (consent_id, user_id, level, status, granted_at, revoked_at, renewal_due,
                     witness_signature, legal_notice_acknowledged, version, audit_trail)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    ON CONFLICT (consent_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        revoked_at = EXCLUDED.revoked_at,
                        audit_trail = EXCLUDED.audit_trail""",
                    record.consent_id, record.user_id, record.level.value,
                    record.status.value, record.granted_at, record.revoked_at,
                    record.renewal_due, record.witness_signature,
                    record.legal_notice_acknowledged, record.version,
                    json.dumps(record.audit_trail, default=str),
                )
        except Exception as e:
            logger.error("Consent persistence failed: %s", e)

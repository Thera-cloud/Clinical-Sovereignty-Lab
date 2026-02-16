"""
Me-2-Me Platinum — Trust Manager
Legal trust-platform integration for Sovereign Legacy Trusts.
Manages trust creation, funding, beneficiaries, guardian succession,
and age-gated access.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.models.me2me import (
    ConsentLevel,
    SovereignLegacyTrust,
    TrustBeneficiary,
)
from app.models.trust import AgeGate, GuardianSuccession, TrustFunding

logger = logging.getLogger("me2me.trust_manager")


class TrustManager:
    """
    Manages Sovereign Legacy Trusts — the legal wrapper around
    Me-2-Me identities that ensures perpetuity and access control.
    """

    def __init__(self, consent_service=None, notifications=None, db_pool=None):
        self._consent = consent_service
        self._notifications = notifications
        self._db = db_pool

    async def create_trust(
        self,
        user_id: str,
        trust_name: str,
        grantor_name: str,
        jurisdiction: str = "US",
        funding_method: str = "subscription",
    ) -> Optional[SovereignLegacyTrust]:
        """Create a new Sovereign Legacy Trust."""
        if self._consent:
            has_consent = await self._consent.check_consent(
                user_id, ConsentLevel.INTERACT
            )
            if not has_consent:
                logger.warning("Trust creation denied: no INTERACT consent for user %s", user_id)
                return None

        trust = SovereignLegacyTrust(
            user_id=user_id,
            trust_name=trust_name,
            grantor_name=grantor_name,
            jurisdiction=jurisdiction,
            funding_method=funding_method,
            established_date=datetime.utcnow(),
            status="active",
        )

        if self._db:
            try:
                async with self._db.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO me2me_sovereign_trusts
                        (trust_id, user_id, trust_name, grantor_name, jurisdiction,
                         funding_method, established_date, status)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                        trust.trust_id, user_id, trust_name, grantor_name,
                        jurisdiction, funding_method, trust.established_date, "active",
                    )
            except Exception as e:
                logger.error("Trust creation failed: %s", e)
                return None

        logger.info("Sovereign Legacy Trust created: user=%s trust=%s", user_id, trust.trust_id)
        return trust

    async def add_beneficiary(
        self,
        trust_id: str,
        name: str,
        relationship: str,
        email: Optional[str] = None,
        age_gate: Optional[int] = None,
        guardian_id: Optional[str] = None,
    ) -> TrustBeneficiary:
        """Add a beneficiary to a trust."""
        beneficiary = TrustBeneficiary(
            trust_id=trust_id,
            name=name,
            relationship=relationship,
            email=email,
            age_gate=age_gate,
            guardian_id=guardian_id,
        )

        if self._db:
            try:
                async with self._db.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO me2me_trust_beneficiaries
                        (beneficiary_id, trust_id, name, relationship, email, age_gate, guardian_id)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                        beneficiary.beneficiary_id, trust_id, name,
                        relationship, email, age_gate, guardian_id,
                    )
            except Exception as e:
                logger.error("Beneficiary addition failed: %s", e)

        return beneficiary

    async def record_funding(
        self,
        trust_id: str,
        amount: float,
        funding_type: str = "subscription",
        stripe_subscription_id: Optional[str] = None,
    ) -> TrustFunding:
        """Record a funding event for a trust."""
        from app.models.trust import FundingType
        funding = TrustFunding(
            trust_id=trust_id,
            funding_type=FundingType(funding_type),
            amount=amount,
            stripe_subscription_id=stripe_subscription_id,
        )

        if self._db:
            try:
                async with self._db.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO me2me_trust_funding
                        (funding_id, trust_id, funding_type, amount, stripe_subscription_id)
                        VALUES ($1, $2, $3, $4, $5)""",
                        funding.funding_id, trust_id, funding_type, amount,
                        stripe_subscription_id,
                    )
            except Exception as e:
                logger.error("Funding record failed: %s", e)

        return funding

    async def check_guardian_succession(self, trust_id: str) -> Optional[GuardianSuccession]:
        """Check guardian succession chain for a trust."""
        if not self._db:
            return None
        try:
            async with self._db.acquire() as conn:
                trust = await conn.fetchrow(
                    "SELECT * FROM me2me_sovereign_trusts WHERE trust_id = $1", trust_id,
                )
                if trust:
                    chain = trust.get("successor_guardian_chain", [])
                    return GuardianSuccession(
                        trust_id=trust_id,
                        primary_guardian_id=chain[0] if chain else "",
                        successor_chain=chain[1:] if len(chain) > 1 else [],
                    )
        except Exception as e:
            logger.error("Guardian succession check failed: %s", e)
        return None

    async def check_age_gate(
        self, beneficiary_id: str, current_age: int
    ) -> AgeGate:
        """Check age gate restrictions for a beneficiary."""
        gate = AgeGate(beneficiary_id=beneficiary_id, current_age=current_age)

        if self._db:
            try:
                async with self._db.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT * FROM me2me_trust_beneficiaries WHERE beneficiary_id = $1",
                        beneficiary_id,
                    )
                    if row and row.get("age_gate"):
                        gate.min_age = row["age_gate"]
                        if current_age < gate.min_age:
                            gate.restricted_topics = row.get("age_gate_content_filters", [])
            except Exception as e:
                logger.error("Age gate check failed: %s", e)

        return gate

"""
SOVEREIGN SWARM — Legacy Vault Billing
Manages long-term storage billing for Me-2-Me data.

Operational Specifications §4.3 — Legacy Vault Billing.
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from app.models.billing_metered import LegacyVaultBilling

logger = logging.getLogger("billing.legacy_vault")


class LegacyVaultBillingService:
    """Manages billing for long-term Me-2-Me data storage."""

    # Cost per GB per month by tier
    TIER_COSTS = {
        "standard": 0.50,
        "archive": 0.25,
        "deep_archive": 0.10,
    }

    def __init__(self, stripe_service=None, db_pool=None):
        self._stripe = stripe_service
        self._db = db_pool

    async def calculate_monthly_cost(self, user_id: str) -> LegacyVaultBilling:
        """Calculate the monthly storage cost for a user's Legacy Vault."""
        billing = await self._get_vault_billing(user_id)
        cost_per_gb = self.TIER_COSTS.get(billing.tier, 0.50)
        billing.monthly_cost = billing.vault_size_gb * cost_per_gb
        return billing

    async def update_vault_size(
        self, user_id: str, size_gb: float
    ) -> LegacyVaultBilling:
        """Update the vault size and recalculate billing."""
        billing = await self._get_vault_billing(user_id)
        billing.vault_size_gb = size_gb
        cost_per_gb = self.TIER_COSTS.get(billing.tier, 0.50)
        billing.monthly_cost = size_gb * cost_per_gb
        await self._persist_vault_billing(billing)
        return billing

    async def migrate_tier(
        self, user_id: str, new_tier: str
    ) -> LegacyVaultBilling:
        """Migrate vault to a different storage tier."""
        if new_tier not in self.TIER_COSTS:
            raise ValueError(f"Invalid tier: {new_tier}")
        billing = await self._get_vault_billing(user_id)
        billing.tier = new_tier
        billing.monthly_cost = billing.vault_size_gb * self.TIER_COSTS[new_tier]
        await self._persist_vault_billing(billing)
        logger.info("Vault tier migrated: user=%s tier=%s", user_id, new_tier)
        return billing

    async def _get_vault_billing(self, user_id: str) -> LegacyVaultBilling:
        return LegacyVaultBilling(user_id=user_id)

    async def _persist_vault_billing(self, billing: LegacyVaultBilling) -> None:
        if not self._db:
            return
        try:
            async with self._db.acquire() as conn:
                await conn.execute(
                    """INSERT INTO legacy_vault_billing (user_id, vault_size_gb, tier, monthly_cost)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (user_id) DO UPDATE SET
                        vault_size_gb = EXCLUDED.vault_size_gb,
                        tier = EXCLUDED.tier,
                        monthly_cost = EXCLUDED.monthly_cost""",
                    billing.user_id, billing.vault_size_gb, billing.tier, billing.monthly_cost,
                )
        except Exception as e:
            logger.error("Vault billing persistence failed: %s", e)

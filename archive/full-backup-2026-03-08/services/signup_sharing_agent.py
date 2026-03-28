"""
Signup Sharing Agent — Daily revenue sharing calculation.

Runs daily at 2:00 AM UTC. For each active signup_code_link, verifies Stripe invoice,
calculates sharing, creates Stripe Transfer, logs to ledger.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger("nate.signup_sharing_agent")

TIER_PRICES = {
    "STANDARD": 4900,
    "TOP_TIER": 14900,
    "TRIAL": 0,
    "COACH_ONLY": 0,
}


class SignupSharingAgent:
    """Background agent that calculates and distributes revenue sharing daily."""

    def __init__(self, db_pool=None, app_state=None):
        self.db_pool = db_pool
        self.app_state = app_state
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("SignupSharingAgent: started (daily 2AM UTC)")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("SignupSharingAgent: stopped")

    async def _run_loop(self):
        await asyncio.sleep(120)
        while self._running:
            now = datetime.now(timezone.utc)
            if now.hour == 2 and now.minute < 30:
                try:
                    await self._run_one_cycle()
                except Exception as e:
                    logger.error("SignupSharingAgent: cycle error: %s", e)
                await asyncio.sleep(3600)
            else:
                await asyncio.sleep(1800)

    async def _run_one_cycle(self):
        """Process all active signup code links for the previous billing period."""
        if not self.db_pool:
            return

        now = datetime.now(timezone.utc)
        period_end = now.date().replace(day=1)
        period_start = (period_end - timedelta(days=1)).replace(day=1)

        async with self.db_pool.acquire() as conn:
            active_links = await conn.fetch(
                """SELECT l.id, l.code_id, l.entity_type, l.entity_id,
                          c.coach_id, c.sharing_pct, c.status as code_status,
                          c.monthly_sharing_cap_cents
                   FROM signup_code_links l
                   JOIN coach_signup_codes c ON c.id = l.code_id
                   WHERE l.status = 'active' AND c.status = 'active'"""
            )

            if not active_links:
                return

            coach_totals = {}
            processed = 0

            # Multi-coach split: pre-compute co-sharing coach count per entity
            entity_coach_counts = {}
            for link in active_links:
                key = (link["entity_type"], link["entity_id"])
                entity_coach_counts.setdefault(key, set()).add(link["coach_id"])

            for link in active_links:
                code_id = link["code_id"]
                coach_id = link["coach_id"]
                sharing_pct = link["sharing_pct"]
                entity_id = link["entity_id"]
                entity_type = link["entity_type"]
                cap = link["monthly_sharing_cap_cents"]

                already_processed = await conn.fetchval(
                    """SELECT EXISTS(SELECT 1 FROM signup_sharing_ledger
                       WHERE code_id = $1 AND entity_id = $2
                       AND billing_period_start = $3 AND billing_period_end = $4)""",
                    code_id, entity_id, period_start, period_end,
                )
                if already_processed:
                    continue

                gross_cents = await self._get_invoice_amount(conn, entity_id, period_start, period_end)

                # Multi-coach split: divide sharing_pct by N co-sharing coaches
                n_coaches = len(entity_coach_counts.get((entity_type, entity_id), {coach_id}))
                effective_pct = sharing_pct / max(n_coaches, 1)
                shared_cents = int(gross_cents * effective_pct / 100)

                if coach_id not in coach_totals:
                    coach_totals[coach_id] = {"total": 0, "cap": cap}
                coach_totals[coach_id]["total"] += shared_cents

                if cap and coach_totals[coach_id]["total"] > cap:
                    overflow = coach_totals[coach_id]["total"] - cap
                    shared_cents = max(0, shared_cents - overflow)
                    coach_totals[coach_id]["total"] = cap

                source_note = None
                if gross_cents == 0:
                    source_note = self._determine_zero_reason(entity_id)
                if n_coaches > 1:
                    source_note = (source_note or "") + f" split:{n_coaches}"

                status = "pending"
                stripe_transfer_id = None

                if shared_cents > 0:
                    profile = await conn.fetchrow(
                        "SELECT profile_data FROM users WHERE hardware_id = $1 AND role = 'COACH'",
                        coach_id,
                    )
                    if profile:
                        pd = profile["profile_data"]
                        if isinstance(pd, str):
                            pd = json.loads(pd)
                        stripe_connect = pd.get("stripe_connect_id")

                        if stripe_connect:
                            stripe_transfer_id = await self._create_transfer(
                                shared_cents, stripe_connect, code_id, entity_id, period_start
                            )
                            if stripe_transfer_id:
                                status = "completed"

                await conn.execute(
                    """INSERT INTO signup_sharing_ledger
                       (code_id, coach_id, entity_id, entity_type, source_type,
                        gross_amount_cents, sharing_pct, shared_amount_cents,
                        billing_period_start, billing_period_end,
                        stripe_transfer_id, status, source_note)
                       VALUES ($1, $2, $3, $4, 'subscription', $5, $6, $7, $8, $9, $10, $11, $12)""",
                    code_id, coach_id, entity_id, entity_type,
                    gross_cents, effective_pct, shared_cents,
                    period_start, period_end,
                    stripe_transfer_id, status, source_note,
                )
                processed += 1

            # DOJO sharing for master coaches (Loophole #6, #7)
            dojo_processed = await self._process_dojo_sharing(conn, period_start, period_end)

            logger.info(
                "SignupSharingAgent: cycle complete — %d subscription entries, %d DOJO entries",
                processed, dojo_processed,
            )

    async def _get_invoice_amount(self, conn, entity_id: str, period_start, period_end) -> int:
        """Get actual Stripe invoice amount for an entity in a billing period.
        Loophole #10: only paid invoices count. Loophole #15: actual amount, not list price."""
        try:
            import stripe
            stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
            if not stripe.api_key:
                return self._estimate_from_tier(conn, entity_id)

            customer_row = await conn.fetchrow(
                "SELECT profile_data->>'stripe_customer_id' as cid FROM users WHERE username = $1",
                entity_id,
            )
            if not customer_row or not customer_row["cid"]:
                return 0

            invoices = stripe.Invoice.list(
                customer=customer_row["cid"],
                status="paid",
                created={"gte": int(datetime.combine(period_start, datetime.min.time()).timestamp()),
                         "lt": int(datetime.combine(period_end, datetime.min.time()).timestamp())},
                limit=5,
            )

            total = sum(inv.amount_paid for inv in invoices.data if inv.amount_paid > 0)
            return total

        except Exception as e:
            logger.warning("SignupSharingAgent: Stripe invoice lookup failed for %s: %s", entity_id, e)
            return 0

    async def _estimate_from_tier(self, conn, entity_id: str) -> int:
        """Fallback: estimate from subscription tier if Stripe is unavailable."""
        row = await conn.fetchrow(
            "SELECT tier FROM users WHERE username = $1", entity_id
        )
        if not row:
            return 0
        return TIER_PRICES.get(row["tier"], 0)

    async def _process_dojo_sharing(self, conn, period_start, period_end) -> int:
        """Process DOJO sharing for master coaches. Loophole #6: re-validate overlap. #7: hierarchy check."""
        hierarchies = await conn.fetch(
            """SELECT h.master_coach_id, h.assistant_id, h.status
               FROM coach_hierarchy h
               WHERE h.status = 'active'"""
        )

        count = 0
        for h in hierarchies:
            master_id = h["master_coach_id"]
            assistant_id = h["assistant_id"]

            master_code = await conn.fetchrow(
                "SELECT id, sharing_pct FROM coach_signup_codes WHERE coach_id = $1 AND status = 'active'",
                master_id,
            )
            if not master_code:
                continue

            master_profile = await conn.fetchrow(
                "SELECT profile_data FROM users WHERE hardware_id = $1 AND role = 'COACH'", master_id
            )
            assistant_profile = await conn.fetchrow(
                "SELECT profile_data FROM users WHERE hardware_id = $1 AND role = 'COACH'", assistant_id
            )

            if not master_profile or not assistant_profile:
                continue

            master_pd = master_profile["profile_data"]
            assistant_pd = assistant_profile["profile_data"]
            if isinstance(master_pd, str):
                master_pd = json.loads(master_pd)
            if isinstance(assistant_pd, str):
                assistant_pd = json.loads(assistant_pd)

            master_dojos = set(self._get_active_dojo_keys(master_pd))
            assistant_dojos = set(self._get_active_dojo_keys(assistant_pd))
            overlap = master_dojos & assistant_dojos

            if not overlap:
                continue

            assistant_subs = assistant_pd.get("dojo_subscriptions", {})

            for dojo_key in overlap:
                sub = assistant_subs.get(dojo_key, {})
                monthly_rate = sub.get("monthly_rate", 0)
                discount_pct = sub.get("discount_pct", 0)
                # Loophole #14: use effective price after discount
                effective = int(monthly_rate * 100 * (1 - discount_pct / 100))

                shared = int(effective * master_code["sharing_pct"] / 100)

                already = await conn.fetchval(
                    """SELECT EXISTS(SELECT 1 FROM signup_sharing_ledger
                       WHERE code_id = $1 AND entity_id = $2 AND source_type = 'dojo'
                       AND billing_period_start = $3)""",
                    master_code["id"], assistant_id, period_start,
                )
                if already:
                    continue

                await conn.execute(
                    """INSERT INTO signup_sharing_ledger
                       (code_id, coach_id, entity_id, entity_type, source_type,
                        gross_amount_cents, sharing_pct, shared_amount_cents,
                        billing_period_start, billing_period_end, status, source_note)
                       VALUES ($1, $2, $3, 'coach', 'dojo', $4, $5, $6, $7, $8, 'pending', $9)""",
                    master_code["id"], master_id, assistant_id,
                    effective, master_code["sharing_pct"], shared,
                    period_start, period_end, f"dojo:{dojo_key}",
                )
                count += 1

        return count

    def _get_active_dojo_keys(self, profile: dict) -> list:
        """Extract active dojo keys from profile."""
        subs = profile.get("dojo_subscriptions", {})
        if not isinstance(subs, dict):
            return []
        active = []
        for key, sub in subs.items():
            if isinstance(sub, dict) and sub.get("status") == "active":
                active.append(key)
        return active

    async def _create_transfer(self, amount_cents: int, destination: str,
                                code_id, entity_id: str, period_start) -> Optional[str]:
        """Create a Stripe Transfer to the coach's connected account."""
        try:
            import stripe
            stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
            if not stripe.api_key:
                return None

            transfer = stripe.Transfer.create(
                amount=amount_cents,
                currency="usd",
                destination=destination,
                metadata={
                    "type": "signup_sharing",
                    "code_id": str(code_id),
                    "entity_id": entity_id,
                    "period": str(period_start),
                },
            )
            return transfer.id

        except Exception as e:
            logger.warning("SignupSharingAgent: Stripe transfer failed: %s", e)
            return None

    def _determine_zero_reason(self, entity_id: str) -> str:
        return "zero_tier"

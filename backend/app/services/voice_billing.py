"""
Voice Therapy Prepaid Billing System (Sovereign Voice v4).

Manages prepaid minute-block accounts, per-second deductions,
PAUSED session recovery, and Stripe recharge checkouts.

SOVEREIGN-VOICE
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("nate.voice_billing")

ADMIN_BYPASS_USER_ID = "DrNevedal1"

STRIPE_VOICE_PRICES = {
    "1block": os.getenv("STRIPE_VOICE_PRICE_1BLOCK", ""),
    "5blocks": os.getenv("STRIPE_VOICE_PRICE_5BLOCKS", ""),
    "10blocks": os.getenv("STRIPE_VOICE_PRICE_10BLOCKS", ""),
    "20blocks": os.getenv("STRIPE_VOICE_PRICE_20BLOCKS", ""),
}

BLOCK_SECONDS = 1200  # 20 minutes per block
PAUSED_TTL_SECONDS = 300  # 5-minute recovery window

SECONDS_MAP = {
    "1block": 1200,
    "5blocks": 6000,
    "10blocks": 12000,
    "20blocks": 24000,
}


class VoiceBillingSystem:
    """Background service for PAUSED session cleanup + billing utilities."""

    def __init__(self, db_pool):
        self._pool = db_pool
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("VoiceBillingSystem started (PAUSED cleanup every 60s)")

    async def stop(self):
        self._running = False
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("VoiceBillingSystem stopped")

    async def _cleanup_loop(self):
        while self._running:
            try:
                await asyncio.sleep(60)
                if not self._running:
                    break
                await cleanup_expired_paused_sessions(self._pool)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("PAUSED cleanup loop error: %s", e)

    # ── Account Queries ──

    async def get_account_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        if not self._pool or not phone:
            return None
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT user_id, phone, balance_seconds, stripe_customer_id "
                    "FROM voice_accounts WHERE phone = $1",
                    phone,
                )
            return dict(row) if row else None
        except Exception as e:
            logger.warning("get_account_by_phone: %s", e)
            return None

    async def get_account_by_user_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        if not self._pool or not user_id:
            return None
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT user_id, phone, balance_seconds, stripe_customer_id "
                    "FROM voice_accounts WHERE user_id = $1",
                    user_id,
                )
            return dict(row) if row else None
        except Exception as e:
            logger.warning("get_account_by_user_id: %s", e)
            return None

    async def get_phone_for_user(self, user_id: str) -> Optional[str]:
        """Look up the phone number for a voice account user."""
        if not self._pool or not user_id:
            return None
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchval(
                    "SELECT phone FROM voice_accounts WHERE user_id = $1",
                    user_id,
                )
            return row
        except Exception as e:
            logger.warning("get_phone_for_user: %s", e)
            return None

    async def is_admin_caller(self, phone: str) -> bool:
        if not self._pool or not phone:
            return False
        from app.services.voice_phone import twilio_lookup_digit_variants
        variants = twilio_lookup_digit_variants(phone)
        if not variants:
            return False
        try:
            async with self._pool.acquire() as conn:
                for v in variants:
                    row = await conn.fetchrow(
                        "SELECT role FROM users "
                        "WHERE regexp_replace(COALESCE(profile_data->>'phone',''), '[^0-9]', '', 'g') = $1 "
                        "AND role = 'ADMIN' LIMIT 1",
                        v,
                    )
                    if row:
                        return True
            return False
        except Exception as e:
            logger.warning("is_admin_caller: %s", e)
            return False

    async def resolve_user_id_for_phone(self, phone: str) -> Optional[str]:
        """Resolve platform users.id::text for a phone number."""
        if not self._pool or not phone:
            return None
        from app.services.voice_phone import twilio_lookup_digit_variants
        variants = twilio_lookup_digit_variants(phone)
        if not variants:
            return None
        try:
            async with self._pool.acquire() as conn:
                for v in variants:
                    row = await conn.fetchrow(
                        "SELECT id::text AS uid FROM users "
                        "WHERE regexp_replace(COALESCE(profile_data->>'phone',''), '[^0-9]', '', 'g') = $1 "
                        "LIMIT 1",
                        v,
                    )
                    if row:
                        return row["uid"]
            return None
        except Exception as e:
            logger.warning("resolve_user_id_for_phone: %s", e)
            return None

    async def resolve_user_name_for_phone(self, phone: str) -> str:
        """Resolve user display name from users table."""
        if not self._pool or not phone:
            return ""
        from app.services.voice_phone import twilio_lookup_digit_variants
        variants = twilio_lookup_digit_variants(phone)
        if not variants:
            return ""
        try:
            async with self._pool.acquire() as conn:
                for v in variants:
                    row = await conn.fetchrow(
                        "SELECT profile_data->>'name' AS name FROM users "
                        "WHERE regexp_replace(COALESCE(profile_data->>'phone',''), '[^0-9]', '', 'g') = $1 "
                        "LIMIT 1",
                        v,
                    )
                    if row and row["name"]:
                        return row["name"]
            return ""
        except Exception as e:
            logger.warning("resolve_user_name_for_phone: %s", e)
            return ""

    # ── Session Management ──

    async def start_session(self, user_id: str, call_sid: str = "") -> Optional[str]:
        if not self._pool:
            return None
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "INSERT INTO voice_sessions (user_id, call_sid, status) "
                    "VALUES ($1, $2, 'active') RETURNING id::text",
                    user_id, call_sid,
                )
            return row["id"] if row else None
        except Exception as e:
            logger.warning("start_session: %s", e)
            return None

    async def end_session(self, session_id: str, end_reason: str = "normal") -> None:
        if not self._pool or not session_id:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "UPDATE voice_sessions SET status = 'completed', "
                    "ended_at = NOW(), end_reason = $2 WHERE id = $1::uuid",
                    session_id, end_reason,
                )
        except Exception as e:
            logger.warning("end_session: %s", e)

    async def pause_session(self, session_id: str) -> None:
        if not self._pool or not session_id:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "UPDATE voice_sessions SET status = 'paused', "
                    "paused_at = NOW() WHERE id = $1::uuid",
                    session_id,
                )
        except Exception as e:
            logger.warning("pause_session: %s", e)

    async def resume_session(self, session_id: str) -> Optional[int]:
        """Resume a paused session. Returns remaining balance."""
        if not self._pool or not session_id:
            return None
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "UPDATE voice_sessions SET status = 'active', paused_at = NULL "
                    "WHERE id = $1::uuid AND status = 'paused' "
                    "RETURNING user_id",
                    session_id,
                )
                if not row:
                    return None
                bal = await conn.fetchval(
                    "SELECT balance_seconds FROM voice_accounts WHERE user_id = $1",
                    row["user_id"],
                )
                return bal
        except Exception as e:
            logger.warning("resume_session: %s", e)
            return None

    async def get_paused_session_for_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        """Find a PAUSED session within the recovery window for a phone."""
        account = await self.get_account_by_phone(phone)
        if not account:
            return None
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id::text AS session_id, user_id, seconds_used "
                    "FROM voice_sessions "
                    "WHERE user_id = $1 AND status = 'paused' "
                    "AND paused_at > NOW() - INTERVAL '5 minutes' "
                    "ORDER BY paused_at DESC LIMIT 1",
                    account["user_id"],
                )
            return dict(row) if row else None
        except Exception as e:
            logger.warning("get_paused_session_for_phone: %s", e)
            return None

    # ── Balance Operations ──

    async def get_balance(self, user_id: str) -> int:
        if not self._pool or not user_id:
            return 0
        try:
            async with self._pool.acquire() as conn:
                val = await conn.fetchval(
                    "SELECT balance_seconds FROM voice_accounts WHERE user_id = $1",
                    user_id,
                )
            return val or 0
        except Exception as e:
            logger.warning("get_balance: %s", e)
            return 0

    async def deduct_seconds(
        self, user_id: str, session_id: str, seconds: int
    ) -> Dict[str, Any]:
        """
        Deduct seconds from balance. Returns status flags:
        - needs_5min_warning: balance < 300s (first time trigger)
        - is_zero: balance hit 0
        - needs_low_balance_alert: balance < 600s
        - remaining: current balance after deduction
        """
        result = {
            "needs_5min_warning": False,
            "is_zero": False,
            "needs_low_balance_alert": False,
            "remaining": 0,
        }
        if not self._pool or not user_id:
            return result
        try:
            async with self._pool.acquire() as conn:
                actual = min(seconds, await self.get_balance(user_id))
                if actual <= 0:
                    result["is_zero"] = True
                    return result

                await conn.execute(
                    "UPDATE voice_accounts SET balance_seconds = "
                    "GREATEST(0, balance_seconds - $2), updated_at = NOW() "
                    "WHERE user_id = $1",
                    user_id, actual,
                )
                await conn.execute(
                    "UPDATE voice_sessions SET seconds_used = seconds_used + $2 "
                    "WHERE id = $1::uuid",
                    session_id, actual,
                )
                await conn.execute(
                    "INSERT INTO voice_transactions (user_id, session_id, type, seconds, description) "
                    "VALUES ($1, $2::uuid, 'deduction', $3, 'call deduction')",
                    user_id, session_id, -actual,
                )
                remaining = await conn.fetchval(
                    "SELECT balance_seconds FROM voice_accounts WHERE user_id = $1",
                    user_id,
                )
                result["remaining"] = remaining or 0
                if remaining == 0:
                    result["is_zero"] = True
                elif remaining <= 300:
                    result["needs_5min_warning"] = True
                if 0 < remaining <= 600:
                    result["needs_low_balance_alert"] = True
        except Exception as e:
            logger.warning("deduct_seconds: %s", e)
        return result

    async def credit_seconds(
        self, user_id: str, phone: str, seconds: int,
        stripe_customer_id: str = "", stripe_payment_id: str = "",
        amount_cents: int = 0,
    ) -> int:
        """Credit seconds to account (creates if needed via UPSERT). Returns new balance."""
        if not self._pool:
            return 0
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "INSERT INTO voice_accounts (user_id, phone, balance_seconds, stripe_customer_id) "
                    "VALUES ($1, $2, $3, $4) "
                    "ON CONFLICT (user_id) DO UPDATE SET "
                    "  balance_seconds = voice_accounts.balance_seconds + EXCLUDED.balance_seconds, "
                    "  stripe_customer_id = COALESCE(EXCLUDED.stripe_customer_id, voice_accounts.stripe_customer_id), "
                    "  updated_at = NOW() "
                    "RETURNING balance_seconds",
                    user_id, phone, seconds, stripe_customer_id or None,
                )
                new_balance = row["balance_seconds"] if row else seconds

                await conn.execute(
                    "INSERT INTO voice_transactions "
                    "(user_id, type, seconds, amount_cents, stripe_payment_id, description) "
                    "VALUES ($1, 'purchase', $2, $3, $4, $5)",
                    user_id, seconds, amount_cents, stripe_payment_id or None,
                    f"Voice block purchase ({seconds // 60} min)",
                )
            return new_balance
        except Exception as e:
            logger.warning("credit_seconds: %s", e)
            return 0

    async def extend_session(self, user_id: str, session_id: str) -> bool:
        """Charge $50 for 1 block (20 min) mid-call. Returns True on success."""
        try:
            import stripe
            account = await self.get_account_by_user_id(user_id)
            if not account or not account.get("stripe_customer_id"):
                return False

            price_id = STRIPE_VOICE_PRICES.get("1block")
            if not price_id:
                logger.warning("extend_session: STRIPE_VOICE_PRICE_1BLOCK not set")
                return False

            intent = stripe.PaymentIntent.create(
                amount=5000,
                currency="usd",
                customer=account["stripe_customer_id"],
                confirm=True,
                automatic_payment_methods={"enabled": True, "allow_redirects": "never"},
                metadata={
                    "type": "voice_extension",
                    "user_id": user_id,
                    "session_id": session_id,
                },
            )

            if intent.status in ("succeeded", "requires_capture"):
                await self.credit_seconds(
                    user_id, account["phone"], BLOCK_SECONDS,
                    stripe_payment_id=intent.id, amount_cents=5000,
                )
                return True
            return False
        except Exception as e:
            logger.warning("extend_session failed: %s", e)
            return False

    async def create_recharge_checkout(
        self, user_id: str, phone: str, pack: str = "1block",
        success_url: str = "", cancel_url: str = "",
    ) -> Optional[str]:
        """Create Stripe Checkout session for voice block purchase. Returns checkout URL."""
        try:
            import stripe
            price_id = STRIPE_VOICE_PRICES.get(pack)
            if not price_id:
                logger.warning("create_recharge_checkout: unknown pack %s", pack)
                return None

            seconds = SECONDS_MAP.get(pack, BLOCK_SECONDS)
            account = await self.get_account_by_user_id(user_id)
            customer_id = account["stripe_customer_id"] if account else None

            params: Dict[str, Any] = {
                "mode": "payment",
                "line_items": [{"price": price_id, "quantity": 1}],
                "metadata": {
                    "type": "voice_block",
                    "user_id": user_id,
                    "phone": phone,
                    "seconds": str(seconds),
                },
                "success_url": success_url or "https://app.sovereignsanctuary.net/voice-recharge-success",
                "cancel_url": cancel_url or "https://app.sovereignsanctuary.net/voice-recharge",
            }
            if customer_id:
                params["customer"] = customer_id

            session = stripe.checkout.Session.create(**params)
            return session.url
        except Exception as e:
            logger.warning("create_recharge_checkout: %s", e)
            return None

    # ── Crystal Recall ──

    async def get_latest_crystal(self, user_id: str) -> Optional[Dict[str, str]]:
        if not self._pool or not user_id:
            return None
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT summary, topics, emotional_state FROM voice_crystals "
                    "WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1",
                    user_id,
                )
            return dict(row) if row else None
        except Exception as e:
            logger.warning("get_latest_crystal: %s", e)
            return None

    # ── Lead Capture ──

    async def record_lead(self, phone: str) -> bool:
        """Record an unknown caller for follow-up. Returns True if this is a new lead."""
        if not self._pool or not phone:
            return False
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "INSERT INTO voice_leads (phone) VALUES ($1) "
                    "ON CONFLICT (phone) DO UPDATE SET "
                    "  call_count = voice_leads.call_count + 1, "
                    "  last_call_at = NOW() "
                    "RETURNING (xmax = 0) AS is_new",
                    phone,
                )
            return row["is_new"] if row else False
        except Exception as e:
            logger.warning("record_lead: %s", e)
            return False

    async def mark_lead_sms_sent(self, phone: str) -> None:
        if not self._pool or not phone:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "UPDATE voice_leads SET sms_sent = TRUE WHERE phone = $1",
                    phone,
                )
        except Exception as e:
            logger.warning("mark_lead_sms_sent: %s", e)


async def cleanup_expired_paused_sessions(pool) -> int:
    """Finalize PAUSED sessions that exceeded the 5-minute recovery window."""
    if not pool:
        return 0
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "UPDATE voice_sessions SET status = 'expired', "
                "ended_at = NOW(), end_reason = 'paused_timeout' "
                "WHERE status = 'paused' "
                "AND paused_at < NOW() - INTERVAL '5 minutes' "
                "RETURNING id::text, user_id"
            )
        if rows:
            logger.info("Cleaned up %d expired PAUSED sessions", len(rows))
        return len(rows)
    except Exception as e:
        logger.warning("cleanup_expired_paused_sessions: %s", e)
        return 0

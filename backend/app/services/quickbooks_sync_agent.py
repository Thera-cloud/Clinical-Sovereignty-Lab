"""QuickBooks Sync Agent — syncs 5 financial streams to QB Online every 6 hours."""

import os
import asyncio
import base64
import random
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

import aiohttp

try:
    from app.secure_logger import get_secure_logger
except ImportError:
    from backend.app.secure_logger import get_secure_logger

try:
    from app.services.skyeye_platform_base import TokenCipher
except ImportError:
    from backend.app.services.skyeye_platform_base import TokenCipher

logger = get_secure_logger(__name__)

_cipher = TokenCipher.get()

QB_CLIENT_ID = os.getenv("QB_CLIENT_ID", "")
QB_CLIENT_SECRET = os.getenv("QB_CLIENT_SECRET", "")
QB_ENVIRONMENT = os.getenv("QB_ENVIRONMENT", "sandbox")

QB_API_BASE = (
    "https://quickbooks.api.intuit.com"
    if QB_ENVIRONMENT == "production"
    else "https://sandbox-quickbooks.api.intuit.com"
)
QB_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

SYNC_INTERVAL_SECONDS = 6 * 3600  # 6 hours
BATCH_SIZE = 50


class QuickBooksSyncAgent:
    """Background agent that syncs financial data to QuickBooks Online."""

    def __init__(self, db_pool=None, app_state=None):
        self._pool = db_pool
        self._app_state = app_state
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        if not self._pool:
            logger.warning("QuickBooksSyncAgent: no db_pool, skipping start")
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("QuickBooksSyncAgent: started (6h cycle)")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("QuickBooksSyncAgent: stopped")

    async def _run_loop(self):
        await asyncio.sleep(300)  # 5-min startup delay
        while self._running:
            try:
                await self._run_one_cycle()
            except Exception as e:
                logger.error("QuickBooksSyncAgent: cycle error: %s", e)
            await asyncio.sleep(SYNC_INTERVAL_SECONDS)

    async def _run_one_cycle(self):
        conn_info = await self._get_connection()
        if not conn_info:
            logger.info("QuickBooksSyncAgent: no QB connection, skipping cycle")
            return

        access_token = await self._ensure_valid_token(conn_info)
        if not access_token:
            logger.warning("QuickBooksSyncAgent: could not obtain valid token")
            return

        realm_id = conn_info["realm_id"]
        totals = {"subscription": 0, "token_purchase": 0, "gkm_donation": 0, "coach_payout": 0, "corporate_invoice": 0}

        async with aiohttp.ClientSession() as session:
            totals["subscription"] = await self._sync_subscriptions(session, access_token, realm_id)
            totals["token_purchase"] = await self._sync_token_purchases(session, access_token, realm_id)
            totals["gkm_donation"] = await self._sync_gkm_donations(session, access_token, realm_id)
            totals["coach_payout"] = await self._sync_coach_payouts(session, access_token, realm_id)
            totals["corporate_invoice"] = await self._sync_corporate_invoices(session, access_token, realm_id)

        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE qb_connection SET last_sync_at = $1, error_message = NULL",
                datetime.now(timezone.utc),
            )

        total_synced = sum(totals.values())
        logger.info(
            "QuickBooksSyncAgent: cycle complete — %d records synced (%s)",
            total_synced,
            ", ".join(f"{k}={v}" for k, v in totals.items()),
        )

    async def _get_connection(self) -> Optional[Dict]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM qb_connection LIMIT 1")
        return dict(row) if row else None

    async def _ensure_valid_token(self, conn_info: Dict) -> Optional[str]:
        expiry = conn_info.get("token_expiry")
        now = datetime.now(timezone.utc)

        access_token = _cipher.decrypt(conn_info["access_token"])
        refresh_token = _cipher.decrypt(conn_info.get("refresh_token", ""))

        if expiry and (expiry - now).total_seconds() > 300:
            return access_token

        if not QB_CLIENT_ID or not QB_CLIENT_SECRET:
            logger.warning("QuickBooksSyncAgent: QB credentials missing, cannot refresh token")
            return None

        if not refresh_token:
            return None

        auth_header = base64.b64encode(f"{QB_CLIENT_ID}:{QB_CLIENT_SECRET}".encode()).decode()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    QB_TOKEN_URL,
                    headers={
                        "Authorization": f"Basic {auth_header}",
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Accept": "application/json",
                    },
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                    },
                ) as resp:
                    if resp.status != 200:
                        logger.error("QuickBooksSyncAgent: token refresh failed: status=%d", resp.status)
                        async with self._pool.acquire() as conn:
                            await conn.execute(
                                "UPDATE qb_connection SET error_message = $1",
                                f"Token refresh failed: {resp.status}",
                            )
                        return None
                    tokens = await resp.json()
        except Exception as e:
            logger.error("QuickBooksSyncAgent: token refresh exception: %s", e)
            return None

        new_expiry = now + timedelta(seconds=tokens.get("expires_in", 3600))
        enc_access = _cipher.encrypt(tokens["access_token"])
        new_raw_refresh = tokens.get("refresh_token", refresh_token)
        enc_refresh = _cipher.encrypt(new_raw_refresh)
        refresh_renewed = new_raw_refresh != refresh_token
        async with self._pool.acquire() as conn:
            if refresh_renewed:
                await conn.execute(
                    """UPDATE qb_connection SET
                         access_token = $1, refresh_token = $2,
                         token_expiry = $3, refresh_token_issued_at = $4,
                         error_message = NULL""",
                    enc_access,
                    enc_refresh,
                    new_expiry,
                    now,
                )
            else:
                await conn.execute(
                    """UPDATE qb_connection SET
                         access_token = $1, refresh_token = $2,
                         token_expiry = $3, error_message = NULL""",
                    enc_access,
                    enc_refresh,
                    new_expiry,
                )

        return tokens["access_token"]

    async def _qb_api(
        self, session: aiohttp.ClientSession, method: str, path: str,
        access_token: str, realm_id: str, json_body: Optional[Dict] = None,
    ) -> Optional[Dict]:
        url = f"{QB_API_BASE}/v3/company/{realm_id}/{path}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            async with session.request(method, url, headers=headers, json=json_body) as resp:
                if resp.status in (200, 201):
                    return await resp.json()
                logger.warning("QB API %s %s → %d", method, path, resp.status)
                return None
        except Exception as e:
            logger.warning("QB API %s %s error: %s", method, path, e)
            return None

    async def _qb_api_with_retry(
        self, session: aiohttp.ClientSession, method: str, path: str,
        access_token: str, realm_id: str, json_body=None,
        max_retries: int = 3, base_delay: float = 1.0, max_delay: float = 30.0,
    ) -> Optional[Dict]:
        for attempt in range(max_retries + 1):
            result = await self._qb_api(session, method, path, access_token, realm_id, json_body)
            if result is not None:
                return result
            if attempt < max_retries:
                delay = min(base_delay * (2 ** attempt), max_delay)
                jitter = random.uniform(0, delay * 0.1)
                await asyncio.sleep(delay + jitter)
        return None

    async def _log_sync(self, conn, sync_type: str, source_table: str, source_id,
                         qb_entity_type: str, qb_entity_id: str, amount_cents: int,
                         status: str = "synced", error_message: str = None):
        await conn.execute(
            """INSERT INTO qb_sync_log
               (sync_type, source_table, source_id, qb_entity_type, qb_entity_id,
                amount_cents, status, error_message)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
            sync_type, source_table, source_id, qb_entity_type,
            qb_entity_id or "", amount_cents, status, error_message,
        )

    # ── Stream 1: Subscriptions → QB Invoice ─────────────────────────────────

    async def _sync_subscriptions(self, session, token, realm_id) -> int:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, username, amount_cents, status, period_start, period_end, created_at
                   FROM payment_history
                   WHERE synced_to_qb = FALSE AND status = 'PAID'
                   ORDER BY created_at LIMIT $1""",
                BATCH_SIZE,
            )

        synced = 0
        for r in rows:
            invoice_body = {
                "Line": [{
                    "Amount": r["amount_cents"] / 100.0,
                    "DetailType": "SalesItemLineDetail",
                    "SalesItemLineDetail": {"ItemRef": {"name": "Subscription"}},
                    "Description": f"Subscription — {r['username']}",
                }],
                "CustomerRef": {"name": r["username"]},
            }
            result = await self._qb_api(session, "POST", "invoice", token, realm_id, invoice_body)
            async with self._pool.acquire() as conn:
                if result:
                    qb_id = result.get("Invoice", {}).get("Id", "")
                    await conn.execute("UPDATE payment_history SET synced_to_qb = TRUE WHERE id = $1", r["id"])
                    await self._log_sync(conn, "subscription", "payment_history", r["id"],
                                         "Invoice", qb_id, r["amount_cents"])
                    synced += 1
                else:
                    await self._log_sync(conn, "subscription", "payment_history", r["id"],
                                         "Invoice", "", r["amount_cents"], "failed", "QB API error")
        return synced

    # ── Stream 2: Token Purchases → QB Sales Receipt ─────────────────────────

    async def _sync_token_purchases(self, session, token, realm_id) -> int:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, username, amount, reason, created_at
                   FROM token_transactions
                   WHERE synced_to_qb = FALSE AND action = 'purchase' AND source = 'token_pack'
                   ORDER BY created_at LIMIT $1""",
                BATCH_SIZE,
            )

        synced = 0
        for r in rows:
            price_cents = self._token_pack_price(r["amount"])
            receipt_body = {
                "Line": [{
                    "Amount": price_cents / 100.0,
                    "DetailType": "SalesItemLineDetail",
                    "SalesItemLineDetail": {"ItemRef": {"name": "Token Pack"}},
                    "Description": f"Token Pack ({r['amount']} tokens) — {r['username']}",
                }],
                "CustomerRef": {"name": r["username"]},
            }
            result = await self._qb_api(session, "POST", "salesreceipt", token, realm_id, receipt_body)
            async with self._pool.acquire() as conn:
                if result:
                    qb_id = result.get("SalesReceipt", {}).get("Id", "")
                    await conn.execute("UPDATE token_transactions SET synced_to_qb = TRUE WHERE id = $1", r["id"])
                    await self._log_sync(conn, "token_purchase", "token_transactions", r["id"],
                                         "SalesReceipt", qb_id, price_cents)
                    synced += 1
                else:
                    await self._log_sync(conn, "token_purchase", "token_transactions", r["id"],
                                         "SalesReceipt", "", price_cents, "failed", "QB API error")
        return synced

    @staticmethod
    def _token_pack_price(token_amount: int) -> int:
        packs = {15000: 300, 50000: 700, 150000: 2000, 1000000: 12500}
        return packs.get(token_amount, 0)

    # ── Stream 3: GKM Donations → QB Journal Entry ───────────────────────────

    async def _sync_gkm_donations(self, session, token, realm_id) -> int:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, username, donation_amount_cents, created_at
                   FROM gkm_donations
                   WHERE synced_to_qb = FALSE
                   ORDER BY created_at LIMIT $1""",
                BATCH_SIZE,
            )

        synced = 0
        for r in rows:
            amount = r["donation_amount_cents"] / 100.0
            je_body = {
                "Line": [
                    {
                        "Amount": amount,
                        "DetailType": "JournalEntryLineDetail",
                        "JournalEntryLineDetail": {
                            "PostingType": "Debit",
                            "AccountRef": {"name": "Stripe Clearing"},
                        },
                        "Description": f"GKM donation from {r['username']}",
                    },
                    {
                        "Amount": amount,
                        "DetailType": "JournalEntryLineDetail",
                        "JournalEntryLineDetail": {
                            "PostingType": "Credit",
                            "AccountRef": {"name": "GKM Donation Revenue"},
                        },
                    },
                ],
            }
            result = await self._qb_api(session, "POST", "journalentry", token, realm_id, je_body)
            async with self._pool.acquire() as conn:
                if result:
                    qb_id = result.get("JournalEntry", {}).get("Id", "")
                    await conn.execute("UPDATE gkm_donations SET synced_to_qb = TRUE WHERE id = $1", r["id"])
                    await self._log_sync(conn, "gkm_donation", "gkm_donations", r["id"],
                                         "JournalEntry", qb_id, r["donation_amount_cents"])
                    synced += 1
                else:
                    await self._log_sync(conn, "gkm_donation", "gkm_donations", r["id"],
                                         "JournalEntry", "", r["donation_amount_cents"], "failed", "QB API error")
        return synced

    # ── Stream 4: Coach Payouts → QB Bill ────────────────────────────────────

    async def _sync_coach_payouts(self, session, token, realm_id) -> int:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT sl.id, sl.coach_id, sl.shared_amount_cents, sl.billing_period_start,
                          sl.billing_period_end, sl.source_note, u.username as coach_username
                   FROM signup_sharing_ledger sl
                   LEFT JOIN users u ON u.hardware_id = sl.coach_id AND u.role = 'COACH'
                   WHERE sl.synced_to_qb = FALSE AND sl.status = 'completed'
                   ORDER BY sl.created_at LIMIT $1""",
                BATCH_SIZE,
            )

        synced = 0
        for r in rows:
            coach_name = r["coach_username"] or r["coach_id"]
            bill_body = {
                "Line": [{
                    "Amount": r["shared_amount_cents"] / 100.0,
                    "DetailType": "AccountBasedExpenseLineDetail",
                    "AccountBasedExpenseLineDetail": {
                        "AccountRef": {"name": "Coach Payouts"},
                    },
                    "Description": f"Revenue share — {coach_name} ({r['billing_period_start']} to {r['billing_period_end']})",
                }],
                "VendorRef": {"name": coach_name},
            }
            result = await self._qb_api(session, "POST", "bill", token, realm_id, bill_body)
            async with self._pool.acquire() as conn:
                if result:
                    qb_id = result.get("Bill", {}).get("Id", "")
                    await conn.execute("UPDATE signup_sharing_ledger SET synced_to_qb = TRUE WHERE id = $1", r["id"])
                    await self._log_sync(conn, "coach_payout", "signup_sharing_ledger", r["id"],
                                         "Bill", qb_id, r["shared_amount_cents"])
                    synced += 1
                else:
                    await self._log_sync(conn, "coach_payout", "signup_sharing_ledger", r["id"],
                                         "Bill", "", r["shared_amount_cents"], "failed", "QB API error")
        return synced

    # ── Stream 5: Corporate Invoices → QB Invoice ────────────────────────────

    async def _sync_corporate_invoices(self, session, token, realm_id) -> int:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT ph.id, ph.amount_cents, ph.created_at, cs.company_name
                   FROM payment_history ph
                   JOIN corporate_enrollments ce ON ce.user_id = (
                       SELECT id FROM users WHERE username = ph.username LIMIT 1
                   )
                   JOIN corporate_sponsors cs ON cs.id = ce.sponsor_id
                   WHERE ph.synced_to_qb = FALSE AND ph.status = 'PAID'
                     AND cs.pays_full = TRUE
                   ORDER BY ph.created_at LIMIT $1""",
                BATCH_SIZE,
            )

        synced = 0
        for r in rows:
            invoice_body = {
                "Line": [{
                    "Amount": r["amount_cents"] / 100.0,
                    "DetailType": "SalesItemLineDetail",
                    "SalesItemLineDetail": {"ItemRef": {"name": "Corporate Subscription"}},
                    "Description": f"Corporate enrollment — {r['company_name']}",
                }],
                "CustomerRef": {"name": r["company_name"]},
            }
            result = await self._qb_api(session, "POST", "invoice", token, realm_id, invoice_body)
            async with self._pool.acquire() as conn:
                if result:
                    qb_id = result.get("Invoice", {}).get("Id", "")
                    await conn.execute("UPDATE payment_history SET synced_to_qb = TRUE WHERE id = $1", r["id"])
                    await self._log_sync(conn, "corporate_invoice", "payment_history", r["id"],
                                         "Invoice", qb_id, r["amount_cents"])
                    synced += 1
                else:
                    await self._log_sync(conn, "corporate_invoice", "payment_history", r["id"],
                                         "Invoice", "", r["amount_cents"], "failed", "QB API error")
        return synced

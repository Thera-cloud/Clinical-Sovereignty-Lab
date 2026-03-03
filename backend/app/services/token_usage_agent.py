"""
Token Usage Agent — Daily/monthly reset, per-source snapshots, year-end receipt automation.

Runs every 30 minutes. Primary duties:
- Daily (midnight UTC): snapshot per-user, per-source usage into token_usage_snapshots,
  then reset token_usage_today to 0.
- Monthly (1st of month): reset token_usage_month to 0.
- Annually (January 2nd): generate year-end GKM donation receipts for donors >= $250.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("token_usage_agent")

POLL_INTERVAL_SECONDS = 1800  # 30 minutes


class TokenUsageAgent:
    def __init__(self, db_pool, app_state=None):
        self._db_pool = db_pool
        self._app_state = app_state
        self._running = False
        self._task = None
        self._last_daily_reset_date = None
        self._last_monthly_reset_month = None

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("TokenUsageAgent started (30min cycle)")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("TokenUsageAgent stopped")

    async def _run_loop(self):
        await asyncio.sleep(60)
        while self._running:
            try:
                await self._cycle()
            except Exception as e:
                logger.error("TokenUsageAgent cycle error: %s", e)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _cycle(self):
        now = datetime.now(timezone.utc)
        today = now.date()
        current_month = (now.year, now.month)

        if self._last_daily_reset_date != today:
            yesterday = today - timedelta(days=1)
            await self._snapshot_and_reset_daily(yesterday)
            self._last_daily_reset_date = today
            logger.info("Daily token reset completed for %s", yesterday)

        if self._last_monthly_reset_month != current_month and now.day == 1:
            await self._reset_monthly()
            self._last_monthly_reset_month = current_month
            logger.info("Monthly token reset completed for %s-%s", now.year, now.month)

        if now.month == 1 and now.day == 2 and now.hour < 1:
            await self._generate_annual_receipts(now.year - 1)

    async def _snapshot_and_reset_daily(self, snapshot_date):
        """Snapshot per-user, per-source usage then reset daily counters."""
        if not self._db_pool:
            return

        async with self._db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT username,
                       COALESCE((profile_data->>'token_usage_today')::int, 0) as usage_today,
                       COALESCE(token_balance, 0) as balance
                FROM users
                WHERE COALESCE((profile_data->>'token_usage_today')::int, 0) > 0
            """)

            if not rows:
                logger.info("No daily usage to snapshot")
                return

            source_breakdown = await conn.fetch("""
                SELECT username, COALESCE(source, 'unknown') as source,
                       SUM(ABS(amount)) as total_tokens
                FROM token_transactions
                WHERE created_at::date = $1
                  AND amount < 0
                GROUP BY username, source
            """, snapshot_date)

            source_map = {}
            for r in source_breakdown:
                key = r["username"]
                if key not in source_map:
                    source_map[key] = []
                source_map[key].append((r["source"], r["total_tokens"]))

            for row in rows:
                uname = row["username"]
                sources = source_map.get(uname, [("unknown", row["usage_today"])])

                if not sources:
                    sources = [("unknown", row["usage_today"])]

                for source, tokens in sources:
                    await conn.execute("""
                        INSERT INTO token_usage_snapshots
                            (username, snapshot_date, tokens_used, tokens_added, balance_at_snapshot, source)
                        VALUES ($1, $2, $3, 0, $4, $5)
                        ON CONFLICT DO NOTHING
                    """, uname, snapshot_date, tokens, row["balance"], source)

            await conn.execute("""
                UPDATE users
                SET profile_data = jsonb_set(
                    COALESCE(profile_data, '{}'::jsonb),
                    '{token_usage_today}',
                    '0'::jsonb
                )
                WHERE COALESCE((profile_data->>'token_usage_today')::int, 0) > 0
            """)

            await conn.execute("""
                UPDATE users
                SET profile_data = jsonb_set(
                    COALESCE(profile_data, '{}'::jsonb),
                    '{last_token_reset}',
                    to_jsonb($1::text)
                )
            """, str(snapshot_date + timedelta(days=1)))

            logger.info("Snapshotted %d users, reset daily counters", len(rows))

    async def _reset_monthly(self):
        """Reset token_usage_month for all users on 1st of month."""
        if not self._db_pool:
            return

        async with self._db_pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE users
                SET profile_data = jsonb_set(
                    COALESCE(profile_data, '{}'::jsonb),
                    '{token_usage_month}',
                    '0'::jsonb
                )
                WHERE COALESCE((profile_data->>'token_usage_month')::int, 0) > 0
            """)
            logger.info("Monthly token reset: %s", result)

    async def _generate_annual_receipts(self, tax_year: int):
        """Generate year-end GKM donation receipts for donors >= $250."""
        if not self._db_pool:
            return

        async with self._db_pool.acquire() as conn:
            donors = await conn.fetch("""
                SELECT username,
                       SUM(donation_amount_cents) as total_cents
                FROM gkm_donations
                WHERE tax_year = $1
                GROUP BY username
                HAVING SUM(donation_amount_cents) >= 25000
            """, tax_year)

            for donor in donors:
                existing = await conn.fetchrow("""
                    SELECT id FROM gkm_annual_receipts
                    WHERE username = $1 AND tax_year = $2
                """, donor["username"], tax_year)

                if existing:
                    continue

                await conn.execute("""
                    INSERT INTO gkm_annual_receipts
                        (username, tax_year, total_donations_cents, created_at)
                    VALUES ($1, $2, $3, NOW())
                    ON CONFLICT (username, tax_year) DO UPDATE
                    SET total_donations_cents = EXCLUDED.total_donations_cents
                """, donor["username"], tax_year, donor["total_cents"])

                await conn.execute("""
                    UPDATE gkm_donations
                    SET receipt_sent = TRUE, receipt_sent_at = NOW()
                    WHERE username = $1 AND tax_year = $2
                """, donor["username"], tax_year)

            logger.info("Annual GKM receipts: %d donors qualified for tax year %d",
                        len(donors), tax_year)

"""
Iceberg CDC (Change Data Capture) Agent

Polls PostgreSQL for new/changed rows across 10 analytics tables
and pushes them as events to Cloudflare Pipeline HTTP endpoints.
The Pipelines sink those events into Apache Iceberg tables in R2.

This offloads 90%+ of analytical reads from PostgreSQL.

Architecture:
    PostgreSQL → CDC Agent (poll every 60s) → Cloudflare Pipelines (HTTP)
                                                → R2 Data Catalog (Iceberg/Parquet)
                                                → R2 SQL (analytics queries)
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import aiohttp

logger = logging.getLogger("iceberg_cdc_agent")

_CF_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
_cf_api_token = os.getenv("CLOUDFLARE_API_TOKEN", "")


def reload_cf_token(new_token: str):
    """Hot-reload Cloudflare API token without process restart."""
    global _cf_api_token
    _cf_api_token = new_token
    logger.info("Cloudflare API token hot-reloaded (iceberg_cdc)")

CDC_CYCLE_SECONDS = 60

CDC_TABLES = {
    "conversation_history": {
        "pk": "id",
        "ts": "created_at",
        "partition_cols": ["user_id", "event_date"],
        "query": """
            SELECT id, user_id, session_id,
                   CASE WHEN content_encrypted THEN '' ELSE user_text END AS user_text,
                   CASE WHEN content_encrypted THEN '' ELSE ai_text END AS ai_text,
                   word_count_user, word_count_ai,
                   me2me_absorbed, content_encrypted,
                   created_at::text AS created_at,
                   created_at::date::text AS event_date
            FROM conversation_history
            WHERE created_at > $1
            ORDER BY created_at ASC
            LIMIT 500
        """,
    },
    "skyeye_activity": {
        "pk": "id",
        "ts": "created_at",
        "partition_cols": ["type", "event_date"],
        "query": """
            SELECT id, platform, type, content, pillar, severity,
                   created_at::text AS created_at,
                   created_at::date::text AS event_date
            FROM skyeye_activity
            WHERE created_at > $1
            ORDER BY created_at ASC
            LIMIT 500
        """,
    },
    "token_transactions": {
        "pk": "id",
        "ts": "created_at",
        "partition_cols": ["username", "source", "event_date"],
        "query": """
            SELECT id::text AS id, username, action, amount,
                   balance_before, balance_after, reason,
                   initiated_by, source,
                   created_at::text AS created_at,
                   created_at::date::text AS event_date
            FROM token_transactions
            WHERE created_at > $1
            ORDER BY created_at ASC
            LIMIT 500
        """,
    },
    "nevedal_metrics": {
        "pk": "id",
        "ts": "recorded_at",
        "partition_cols": ["user_id", "event_date"],
        "query": """
            SELECT id, user_id::text AS user_id,
                   session_id::text AS session_id,
                   c_emo::float8, p_ent::float8, t_tunnel::float8,
                   gamma_env::float8, e_g_joint::float8,
                   tau_emo::float8, d_distance::float8,
                   cee_window, cee_duration_seconds,
                   recorded_at::text AS recorded_at,
                   recorded_at::date::text AS event_date
            FROM nevedal_metrics
            WHERE recorded_at > $1
            ORDER BY recorded_at ASC
            LIMIT 500
        """,
    },
    "wisdom_extractions": {
        "pk": "id",
        "ts": "extracted_at",
        "partition_cols": ["user_id", "family_id", "insight_type", "event_date"],
        "query": """
            SELECT id::text AS id, user_id::text AS user_id,
                   family_id::text AS family_id,
                   session_id::text AS session_id,
                   insight_type, content, effectiveness_score,
                   source, approved,
                   extracted_at::text AS extracted_at,
                   extracted_at::date::text AS event_date
            FROM wisdom_extractions
            WHERE extracted_at > $1
            ORDER BY extracted_at ASC
            LIMIT 500
        """,
    },
    "me2me_imprint_entries": {
        "pk": "entry_id",
        "ts": "captured_at",
        "partition_cols": ["user_id", "event_date"],
        "query": """
            SELECT entry_id, user_id, source, content,
                   c_emo_at_capture, gamma_at_capture,
                   captured_at::text AS captured_at,
                   processed,
                   captured_at::date::text AS event_date
            FROM me2me_imprint_entries
            WHERE captured_at > $1
            ORDER BY captured_at ASC
            LIMIT 500
        """,
    },
    "skyeye_post_analytics": {
        "pk": "id",
        "ts": "captured_at",
        "partition_cols": ["platform", "event_date"],
        "query": """
            SELECT id, platform, post_id, post_url, post_text,
                   likes, reposts, comments, impressions,
                   captured_at::text AS captured_at,
                   captured_at::date::text AS event_date
            FROM skyeye_post_analytics
            WHERE captured_at > $1
            ORDER BY captured_at ASC
            LIMIT 500
        """,
    },
    "skyeye_notifications": {
        "pk": "id",
        "ts": "created_at",
        "partition_cols": ["platform", "notification_type", "event_date"],
        "query": """
            SELECT id, platform, notification_type, post_id,
                   actor_handle, actor_id, actor_followers,
                   processed,
                   created_at::text AS created_at,
                   created_at::date::text AS event_date
            FROM skyeye_notifications
            WHERE created_at > $1
            ORDER BY created_at ASC
            LIMIT 500
        """,
    },
    "coaching_sessions": {
        "pk": "id",
        "ts": "created_at",
        "partition_cols": ["client_id", "coach_id", "event_date"],
        "query": """
            SELECT id::text AS id, client_id, coach_id, status,
                   payment_amount_cents, duration_minutes,
                   payment_status,
                   COALESCE(scheduled_start, scheduled_at)::text AS scheduled_at,
                   actual_start::text AS started_at,
                   actual_end::text AS ended_at,
                   created_at::text AS created_at,
                   created_at::date::text AS event_date
            FROM coaching_sessions
            WHERE created_at > $1
            ORDER BY created_at ASC
            LIMIT 500
        """,
    },
    "skyeye_sessions": {
        "pk": "id",
        "ts": "created_at",
        "partition_cols": ["status", "event_date"],
        "query": """
            SELECT id, session_start::text AS session_start,
                   session_end::text AS session_end,
                   total_actions, status, notes,
                   created_at::text AS created_at,
                   created_at::date::text AS event_date
            FROM skyeye_sessions
            WHERE created_at > $1
            ORDER BY created_at ASC
            LIMIT 500
        """,
    },
    "nate_intelligence_crystals": {
        "pk": "id",
        "ts": "created_at",
        "partition_cols": ["domain", "event_date"],
        "query": """
            SELECT id, crystal_text, domain, scope, topics,
                   source_count, generation, confidence,
                   content_hash, context_start::text, context_end::text,
                   last_recalled_at::text, recall_count,
                   superseded_by::text,
                   created_at::text AS created_at,
                   created_at::date::text AS event_date
            FROM nate_intelligence_crystals
            WHERE created_at > $1
            ORDER BY created_at ASC
            LIMIT 500
        """,
    },
}


class IcebergCDCAgent:
    """Polls PostgreSQL and pushes CDC events to Cloudflare Pipelines."""

    def __init__(self, db_pool, app_state=None):
        self._db_pool = db_pool
        self._app_state = app_state
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._watermarks: dict[str, datetime] = {}
        self._cycle_count = 0
        self._total_rows_pushed = 0
        self._consecutive_auth_fails = 0
        self._disabled_by_auth = False
        self._auth_failed_this_cycle = False
        self._backoff_seconds = 0

    async def start(self):
        if not _cf_api_token or not _CF_ACCOUNT_ID:
            logger.info("IcebergCDCAgent: CLOUDFLARE_API_TOKEN or CLOUDFLARE_ACCOUNT_ID not set — disabled")
            return
        if not self._db_pool:
            logger.warning("IcebergCDCAgent: no db_pool — disabled")
            return

        self._running = True
        self._session_token = _cf_api_token
        await self._init_watermarks()
        self._session = aiohttp.ClientSession(
            headers={
                "Authorization": f"Bearer {_cf_api_token}",
                "Content-Type": "application/json",
            },
            timeout=aiohttp.ClientTimeout(total=30),
        )

        try:
            verify_url = f"https://api.cloudflare.com/client/v4/accounts/{_CF_ACCOUNT_ID}/r2/buckets"
            async with self._session.get(verify_url) as resp:
                if resp.status == 403:
                    logger.warning(
                        "IcebergCDCAgent: Cloudflare token returned 403 — "
                        "check token scopes (needs Workers R2 Storage, D1 Edit). "
                        "Agent will still start but pushes will fail."
                    )
                elif resp.status == 200:
                    logger.info("IcebergCDCAgent: Cloudflare token verified (200)")
        except Exception as e:
            logger.warning("IcebergCDCAgent: token verification failed: %s", e)

        self._task = asyncio.create_task(self._run_loop())
        logger.info("IcebergCDCAgent: started (%d tables, %ds cycle)", len(CDC_TABLES), CDC_CYCLE_SECONDS)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._session:
            await self._session.close()
        logger.info("IcebergCDCAgent: stopped (pushed %d total rows across %d cycles)", self._total_rows_pushed, self._cycle_count)

    async def _init_watermarks(self):
        """Load last-synced watermarks from DB or default to epoch."""
        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS iceberg_cdc_watermarks (
                        table_name TEXT PRIMARY KEY,
                        last_synced_at TIMESTAMPTZ NOT NULL DEFAULT '2020-01-01T00:00:00Z',
                        rows_synced BIGINT DEFAULT 0,
                        updated_at TIMESTAMPTZ DEFAULT now()
                    )
                """)
                rows = await conn.fetch("SELECT table_name, last_synced_at FROM iceberg_cdc_watermarks")
                for r in rows:
                    self._watermarks[r["table_name"]] = r["last_synced_at"]

            for table in CDC_TABLES:
                if table not in self._watermarks:
                    self._watermarks[table] = datetime(2020, 1, 1, tzinfo=timezone.utc)
                    async with self._db_pool.acquire() as conn:
                        await conn.execute(
                            "INSERT INTO iceberg_cdc_watermarks (table_name) VALUES ($1) ON CONFLICT DO NOTHING",
                            table,
                        )
        except Exception as e:
            logger.warning("IcebergCDCAgent: watermark init failed: %s", e)
            for table in CDC_TABLES:
                self._watermarks.setdefault(table, datetime(2020, 1, 1, tzinfo=timezone.utc))

    async def _run_loop(self):
        await asyncio.sleep(5)
        while self._running:
            if self._disabled_by_auth:
                await asyncio.sleep(3600)
                self._disabled_by_auth = False
                self._consecutive_auth_fails = 0
                self._backoff_seconds = 0
                logger.info("IcebergCDCAgent: resuming after 1-hour auth suspension")
                continue

            self._auth_failed_this_cycle = False
            try:
                await self._poll_cycle()
                self._cycle_count += 1
                if not self._auth_failed_this_cycle:
                    self._backoff_seconds = 0
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("IcebergCDCAgent: cycle error: %s", e)

            delay = CDC_CYCLE_SECONDS + self._backoff_seconds
            await asyncio.sleep(delay)

    async def _poll_cycle(self):
        """Poll all 10 tables for new rows since watermark."""
        cycle_total = 0
        for table_name, cfg in CDC_TABLES.items():
            if self._auth_failed_this_cycle or self._disabled_by_auth:
                break
            try:
                rows_pushed = await self._poll_table(table_name, cfg)
                cycle_total += rows_pushed
            except Exception as e:
                logger.warning("IcebergCDCAgent: %s poll failed: %s", table_name, e)

        if cycle_total > 0:
            self._total_rows_pushed += cycle_total
            logger.info("IcebergCDCAgent: cycle %d pushed %d rows (%d cumulative)",
                        self._cycle_count + 1, cycle_total, self._total_rows_pushed)

    async def _poll_table(self, table_name: str, cfg: dict) -> int:
        """Poll a single table and push new rows to Cloudflare Pipeline."""
        watermark = self._watermarks.get(table_name, datetime(2020, 1, 1, tzinfo=timezone.utc))

        async with self._db_pool.acquire() as conn:
            rows = await conn.fetch(cfg["query"], watermark)

        if not rows:
            return 0

        events = []
        max_ts = watermark
        for row in rows:
            record = dict(row)
            record["cdc_op"] = "INSERT"
            for k, v in record.items():
                if isinstance(v, datetime):
                    record[k] = v.isoformat()
                elif v is None:
                    record[k] = None
            events.append(record)

            ts_col = cfg["ts"]
            row_ts = row.get(ts_col)
            if row_ts and isinstance(row_ts, str):
                try:
                    row_ts = datetime.fromisoformat(row_ts.replace("+00:00", "+00:00").replace("Z", "+00:00"))
                except Exception:
                    row_ts = None
            if row_ts and row_ts > max_ts:
                max_ts = row_ts

        pushed = await self._push_to_pipeline(table_name, events)
        if pushed:
            self._watermarks[table_name] = max_ts
            try:
                async with self._db_pool.acquire() as conn:
                    await conn.execute(
                        """UPDATE iceberg_cdc_watermarks
                           SET last_synced_at = $1, rows_synced = rows_synced + $2, updated_at = now()
                           WHERE table_name = $3""",
                        max_ts, len(events), table_name,
                    )
            except Exception as e:
                logger.warning("IcebergCDCAgent: watermark update failed for %s: %s", table_name, e)

        return len(events) if pushed else 0

    async def _refresh_session_if_needed(self):
        if hasattr(self, '_session_token') and self._session_token != _cf_api_token:
            if self._session and not self._session.closed:
                await self._session.close()
            self._session_token = _cf_api_token
            self._session = aiohttp.ClientSession(
                headers={"Authorization": f"Bearer {_cf_api_token}", "Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=30),
            )
            logger.info("IcebergCDCAgent: session refreshed with new CF token")

    async def _push_to_pipeline(self, table_name: str, events: list[dict]) -> bool:
        """Push events to the Cloudflare Pipeline HTTP endpoint."""
        if self._disabled_by_auth or self._auth_failed_this_cycle:
            return False
        await self._refresh_session_if_needed()
        if not self._session:
            return False

        stream_name = f"cdc_{table_name}_stream"
        url = f"https://api.cloudflare.com/client/v4/accounts/{_CF_ACCOUNT_ID}/pipelines/streams/{stream_name}/events"

        try:
            async with self._session.post(url, json=events) as resp:
                if resp.status in (200, 201, 202):
                    self._consecutive_auth_fails = 0
                    return True
                if resp.status in (401, 403):
                    self._consecutive_auth_fails += 1
                    self._auth_failed_this_cycle = True
                    if self._consecutive_auth_fails >= 3:
                        logger.error(
                            "IcebergCDCAgent: %d consecutive auth failures (%d) — "
                            "suspending for 1 hour. Check CLOUDFLARE_API_TOKEN scopes.",
                            self._consecutive_auth_fails, resp.status,
                        )
                        self._disabled_by_auth = True
                    return False
                if resp.status == 429:
                    self._auth_failed_this_cycle = True
                    retry_after = int(resp.headers.get("Retry-After", "120"))
                    self._backoff_seconds = min(retry_after, 600)
                    logger.warning("IcebergCDCAgent: rate-limited (429) on %s — backing off %ds",
                                   table_name, self._backoff_seconds)
                    return False
                body = await resp.text()
                logger.warning("IcebergCDCAgent: push %s failed (%d): %s", table_name, resp.status, body[:200])
                return False
        except Exception as e:
            logger.warning("IcebergCDCAgent: push %s error: %s", table_name, e)
            return False

    async def backfill(self, table_name: str = None, since: datetime = None):
        """
        Manual backfill — resets watermark and re-syncs.
        Call from an admin endpoint or script.
        """
        target = since or datetime(2020, 1, 1, tzinfo=timezone.utc)
        tables = [table_name] if table_name else list(CDC_TABLES.keys())

        total = 0
        for t in tables:
            if t not in CDC_TABLES:
                logger.warning("IcebergCDCAgent: unknown table %s", t)
                continue
            self._watermarks[t] = target
            try:
                async with self._db_pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE iceberg_cdc_watermarks SET last_synced_at = $1, updated_at = now() WHERE table_name = $2",
                        target, t,
                    )
            except Exception:
                pass

            pushed = 0
            while True:
                n = await self._poll_table(t, CDC_TABLES[t])
                pushed += n
                if n < 500:
                    break
            total += pushed
            logger.info("IcebergCDCAgent: backfilled %s — %d rows", t, pushed)

        return {"tables_backfilled": len(tables), "rows_pushed": total}

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "cycle_count": self._cycle_count,
            "total_rows_pushed": self._total_rows_pushed,
            "tables": len(CDC_TABLES),
            "watermarks": {k: v.isoformat() if isinstance(v, datetime) else str(v) for k, v in self._watermarks.items()},
        }

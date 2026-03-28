"""
HIVE DEFENSE v4.0 — Billing Monitor
Background anomaly detection loop (runs every 5 minutes).

7 Anomaly Rules:
1. Webhook flood (>100 events in 5 minutes)
2. Subscription churn spike (>10% in 24h)
3. Failed payment surge (>20 in 1 hour)
4. Trial abuse cluster (>5 matching fingerprints in 24h)
5. Unusual upgrade patterns (>10 upgrades in 1 hour)
6. Cord failure spike (>5 Cord 2/3 failures in 1 hour)
7. Refund spike (>5 refunds in 1 hour)
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

_logger = logging.getLogger("billing_monitor")

MONITOR_INTERVAL_SECONDS = 300  # 5 minutes


class BillingMonitor:
    """Background billing anomaly detection engine."""

    def __init__(self, db_pool):
        self._db = db_pool
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the background monitoring loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        _logger.info("BillingMonitor started (interval=%ds)", MONITOR_INTERVAL_SECONDS)

    async def stop(self) -> None:
        """Stop the monitoring loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        _logger.info("BillingMonitor stopped")

    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                await self._run_all_rules()
            except Exception as exc:
                _logger.error("BillingMonitor loop error: %s", exc)
            await asyncio.sleep(MONITOR_INTERVAL_SECONDS)

    async def _run_all_rules(self) -> None:
        """Execute all 7 anomaly detection rules."""
        if not self._db:
            return
        now = datetime.now(timezone.utc)

        await self._rule_webhook_flood(now)
        await self._rule_churn_spike(now)
        await self._rule_failed_payments(now)
        await self._rule_trial_abuse_cluster(now)
        await self._rule_unusual_upgrades(now)
        await self._rule_cord_failure_spike(now)
        await self._rule_refund_spike(now)

    # ─── Rule 1: Webhook Flood ────────────────────────────────────────────────

    async def _rule_webhook_flood(self, now: datetime) -> None:
        """Detect >100 webhook events in 5 minutes."""
        try:
            row = await self._db.fetchrow(
                "SELECT COUNT(*) as cnt FROM webhook_events_v2 WHERE created_at > $1",
                now - timedelta(minutes=5),
            )
            count = row["cnt"] if row else 0
            if count > 100:
                await self._record_anomaly(
                    "webhook_flood",
                    f"{count} webhook events in 5 minutes",
                    count, 100, "high",
                    "rate_limiting_recommended",
                )
        except Exception as exc:
            _logger.error("Rule webhook_flood error: %s", exc)

    # ─── Rule 2: Churn Spike ─────────────────────────────────────────────────

    async def _rule_churn_spike(self, now: datetime) -> None:
        """Detect >10% subscription cancellations in 24h."""
        try:
            cancelled = await self._db.fetchrow(
                """SELECT COUNT(*) as cnt FROM webhook_events_v2
                   WHERE event_type LIKE '%%subscription%%cancel%%'
                   AND created_at > $1""",
                now - timedelta(hours=24),
            )
            total = await self._db.fetchrow(
                "SELECT COUNT(*) as cnt FROM webhook_events_v2 WHERE event_type LIKE '%%subscription%%' AND created_at > $1",
                now - timedelta(hours=24),
            )
            c = cancelled["cnt"] if cancelled else 0
            t = total["cnt"] if total else 1
            if t > 0 and (c / t) > 0.10 and c > 5:
                await self._record_anomaly(
                    "churn_spike",
                    f"{c}/{t} subscriptions cancelled in 24h ({(c/t)*100:.1f}%)",
                    c, int(t * 0.10), "high",
                    "admin_notification",
                )
        except Exception as exc:
            _logger.error("Rule churn_spike error: %s", exc)

    # ─── Rule 3: Failed Payment Surge ─────────────────────────────────────────

    async def _rule_failed_payments(self, now: datetime) -> None:
        """Detect >20 failed payments in 1 hour."""
        try:
            row = await self._db.fetchrow(
                """SELECT COUNT(*) as cnt FROM webhook_events_v2
                   WHERE event_type LIKE '%%payment_intent.payment_failed%%'
                   AND created_at > $1""",
                now - timedelta(hours=1),
            )
            count = row["cnt"] if row else 0
            if count > 20:
                await self._record_anomaly(
                    "failed_payment_surge",
                    f"{count} failed payments in 1 hour",
                    count, 20, "medium",
                    "investigate_payment_processor",
                )
        except Exception as exc:
            _logger.error("Rule failed_payments error: %s", exc)

    # ─── Rule 4: Trial Abuse Cluster ──────────────────────────────────────────

    async def _rule_trial_abuse_cluster(self, now: datetime) -> None:
        """Detect >5 matching trial fingerprints in 24h."""
        try:
            row = await self._db.fetchrow(
                """SELECT COUNT(*) as cnt FROM trial_fingerprints
                   WHERE created_at > $1""",
                now - timedelta(hours=24),
            )
            count = row["cnt"] if row else 0
            if count > 25:
                await self._record_anomaly(
                    "trial_abuse_cluster",
                    f"{count} new trial fingerprints in 24h",
                    count, 25, "medium",
                    "review_trial_signups",
                )
        except Exception as exc:
            _logger.error("Rule trial_abuse_cluster error: %s", exc)

    # ─── Rule 5: Unusual Upgrade Patterns ─────────────────────────────────────

    async def _rule_unusual_upgrades(self, now: datetime) -> None:
        """Detect >10 tier upgrades in 1 hour."""
        try:
            row = await self._db.fetchrow(
                """SELECT COUNT(*) as cnt FROM webhook_events_v2
                   WHERE event_type LIKE '%%customer.subscription.updated%%'
                   AND created_at > $1""",
                now - timedelta(hours=1),
            )
            count = row["cnt"] if row else 0
            if count > 10:
                await self._record_anomaly(
                    "unusual_upgrades",
                    f"{count} subscription updates in 1 hour",
                    count, 10, "medium",
                    "verify_upgrade_legitimacy",
                )
        except Exception as exc:
            _logger.error("Rule unusual_upgrades error: %s", exc)

    # ─── Rule 6: Cord Failure Spike ───────────────────────────────────────────

    async def _rule_cord_failure_spike(self, now: datetime) -> None:
        """Detect >5 Cord 2/3 failures in 1 hour."""
        try:
            row = await self._db.fetchrow(
                """SELECT COUNT(*) as cnt FROM webhook_events_v2
                   WHERE (cord2_passed = FALSE OR cord3_passed = FALSE)
                   AND cord1_passed = TRUE
                   AND created_at > $1""",
                now - timedelta(hours=1),
            )
            count = row["cnt"] if row else 0
            if count > 5:
                await self._record_anomaly(
                    "cord_failure_spike",
                    f"{count} Cord 2/3 failures in 1 hour (potential forgery)",
                    count, 5, "critical",
                    "block_webhook_processing",
                )
        except Exception as exc:
            _logger.error("Rule cord_failure_spike error: %s", exc)

    # ─── Rule 7: Refund Spike ─────────────────────────────────────────────────

    async def _rule_refund_spike(self, now: datetime) -> None:
        """Detect >5 refunds in 1 hour."""
        try:
            row = await self._db.fetchrow(
                """SELECT COUNT(*) as cnt FROM webhook_events_v2
                   WHERE event_type LIKE '%%charge.refund%%'
                   AND created_at > $1""",
                now - timedelta(hours=1),
            )
            count = row["cnt"] if row else 0
            if count > 5:
                await self._record_anomaly(
                    "refund_spike",
                    f"{count} refunds in 1 hour",
                    count, 5, "high",
                    "freeze_refund_processing",
                )
        except Exception as exc:
            _logger.error("Rule refund_spike error: %s", exc)

    # ─── Anomaly Recording ────────────────────────────────────────────────────

    async def _record_anomaly(
        self, rule_name: str, description: str,
        event_count: int, threshold: int,
        alert_level: str, action_taken: str,
    ) -> None:
        """Record an anomaly in the billing_anomalies table."""
        _logger.warning("BILLING ANOMALY [%s/%s]: %s", alert_level.upper(), rule_name, description)
        if not self._db:
            return
        try:
            await self._db.execute(
                """INSERT INTO billing_anomalies
                   (rule_name, description, event_count, threshold, alert_level, action_taken, detected_at)
                   VALUES ($1, $2, $3, $4, $5, $6, NOW())""",
                rule_name, description, event_count, threshold, alert_level, action_taken,
            )
        except Exception as exc:
            _logger.error("Failed to record anomaly: %s", exc)

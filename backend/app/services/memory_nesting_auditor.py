"""
LITTLE NATE — Memory Nesting Auditor
Verifies every CLIENT across the platform has at least one row in conversation_history.
Alerts when data is not nesting (0 rows for a client).
Scheduled 3x daily (5 AM, 5 PM, 11 PM UTC) with stagger delay of 95s.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("nate.memory_nesting_auditor")

AUDIT_HOURS = {5, 17, 23}
WARNING_THRESHOLD_PCT = 10  # Alert if >10% of clients have 0 rows
SUPPORT_EMAIL = "support@sovereignsanctuary.net"


class MemoryNestingAuditor:

    def __init__(self, db_pool, notification_system=None, app_state=None):
        self.db_pool = db_pool
        self.notifications = notification_system
        self._app_state = app_state
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._sent_windows: set = set()

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("MemoryNestingAuditor started (3x daily at UTC 05:00, 17:00, 23:00)")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("MemoryNestingAuditor stopped")

    async def _run_loop(self):
        await asyncio.sleep(95)
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                window_key = f"{now.date().isoformat()}_{now.hour}"
                if now.hour in AUDIT_HOURS and window_key not in self._sent_windows:
                    await self._build_and_send(now)
                    self._sent_windows.add(window_key)
                    self._sent_windows = {
                        k for k in self._sent_windows
                        if k.startswith(now.date().isoformat())
                    }
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("MemoryNestingAuditor tick failed: %s", e, exc_info=True)
            await asyncio.sleep(60)

    async def _build_and_send(self, now: datetime):
        results = await self._audit_all_clients()

        total_clients = results["total_clients"]
        zero_row_count = len(results["zero_row_hw_ids"])
        zero_row_hw_ids = results["zero_row_hw_ids"]
        is_pre_launch = results.get("pre_launch", False)
        pct_zero = (zero_row_count / total_clients * 100) if total_clients > 0 else 0

        if total_clients == 0:
            status = "TRUSTED"
            detail = "No active clients yet — pre-launch"
            score_content = f"1/1 TRUSTED — {detail}"
        elif is_pre_launch:
            status = "TRUSTED"
            detail = f"Pre-launch: {total_clients} clients registered, conversation_history empty — expected before first sessions"
            score_content = f"1/1 TRUSTED — {detail}"
        elif zero_row_count == 0:
            status = "TRUSTED"
            detail = f"All {total_clients} clients have conversation_history data"
            score_content = f"1/1 TRUSTED — {detail}"
        elif pct_zero <= WARNING_THRESHOLD_PCT:
            status = "TRUSTED"
            detail = f"{zero_row_count}/{total_clients} clients ({pct_zero:.1f}%) have 0 rows — within {WARNING_THRESHOLD_PCT}% tolerance"
            score_content = f"1/1 TRUSTED — {detail}"
        else:
            status = "FAILED"
            detail = f"{zero_row_count}/{total_clients} clients ({pct_zero:.1f}%) have 0 rows — exceeds {WARNING_THRESHOLD_PCT}%"
            score_content = f"0/1 TRUSTED — {detail} (see metadata)"

        payload = {
            "total_clients": total_clients,
            "zero_row_count": zero_row_count,
            "zero_row_hw_ids": zero_row_hw_ids[:50],
            "pct_zero": round(pct_zero, 2),
            "status": status,
            "timestamp": now.isoformat(),
        }
        await self._log_activity(
            "system", "memory_nesting_audit_sent",
            score_content,
            "success" if status == "TRUSTED" else ("warning" if status == "WARNING" else "error"),
            json.dumps(payload, default=str),
        )
        logger.info("MemoryNestingAuditor: %s — %s", status, detail)

        if status != "TRUSTED" and self.notifications and zero_row_hw_ids:
            await self._send_alert_email(
                total_clients, zero_row_count, zero_row_hw_ids, pct_zero, status,
            )

    async def _audit_all_clients(self) -> dict:
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT username, hardware_id FROM users
                       WHERE role = 'CLIENT' AND deleted_at IS NULL
                       AND hardware_id IS NOT NULL AND hardware_id != ''
                       AND username NOT LIKE 'audit_%'
                       AND username NOT LIKE 'loadtest_%'"""
                )
                total = len(rows)

                if total == 0:
                    return {"total_clients": 0, "zero_row_hw_ids": []}

                total_history = await conn.fetchval(
                    "SELECT COUNT(*) FROM conversation_history"
                ) or 0
                if total_history == 0:
                    return {
                        "total_clients": total,
                        "zero_row_hw_ids": [],
                        "pre_launch": True,
                    }

                zero_row_hw_ids = []
                for row in rows:
                    hw_id = row["hardware_id"]
                    uname = row["username"]
                    count = await conn.fetchval(
                        "SELECT COUNT(*) FROM conversation_history WHERE user_id = $1 OR user_id = $2",
                        hw_id, uname,
                    )
                    if (count or 0) == 0:
                        zero_row_hw_ids.append(hw_id)

                return {
                    "total_clients": total,
                    "zero_row_hw_ids": zero_row_hw_ids,
                }
        except Exception as e:
            logger.warning("MemoryNestingAuditor: audit failed: %s", e)
            return {"total_clients": 0, "zero_row_hw_ids": []}

    async def _send_alert_email(
        self, total: int, zero_count: int, hw_ids: list, pct: float, status: str
    ):
        try:
            ids_preview = ", ".join(hw_ids[:20])
            if len(hw_ids) > 20:
                ids_preview += f" ... and {len(hw_ids) - 20} more"
            subject = f"[Memory Nesting {status}] {zero_count}/{total} clients have no conversation_history"
            body = f"""<p>Memory Nesting Auditor Alert</p>
<p><strong>Status:</strong> {status}<br>
<strong>Total clients:</strong> {total}<br>
<strong>Clients with 0 rows in conversation_history:</strong> {zero_count} ({pct:.1f}%)</p>
<p><strong>Affected hardware_ids (sample):</strong><br>{ids_preview}</p>
<p>Action: Verify bridge db_pool is writing; run backfill for users with memory.json.</p>"""
            await self.notifications._send_email(
                SUPPORT_EMAIL, subject, body, "memory_nesting_alert"
            )
        except Exception as e:
            logger.warning("MemoryNestingAuditor: alert email failed: %s", e)

    async def _log_activity(
        self, platform: str, activity_type: str,
        content: str, severity: str = "info",
        detail: str = "",
    ):
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO skyeye_activity (platform, type, content, severity,
                                                metadata, created_at)
                    VALUES ($1, $2, $3, $4, $5::jsonb, NOW())
                    """,
                    platform, activity_type, content, severity,
                    detail if detail else "{}",
                )
        except Exception:
            pass

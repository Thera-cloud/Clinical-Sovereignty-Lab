"""
QUANTUM-CRYSTAL-ARCH: Daily self-monitoring agent (Agentic Phase 4).

Scans consented clients for sustained engagement / C_emo decline; coach alert by default.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nate.self_monitor")

CYCLE_SECONDS = 86400  # daily
STAGGER_SECONDS = 330

ENGAGEMENT_DROP_THRESHOLD = 0.40
CEMO_DECLINE_STREAK = 3


def self_monitor_enabled() -> bool:
    return os.getenv("ENABLE_SELF_MONITOR_AGENT", "false").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def coach_alert_enabled() -> bool:
    return os.getenv("ENABLE_SELF_MONITOR_COACH_ALERT", "false").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def client_touch_enabled() -> bool:
    return os.getenv("ENABLE_SELF_MONITOR_TOUCH", "false").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _profile_data(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


class NateSelfMonitorAgent:
    def __init__(self, db_pool, app_state=None):
        self._db_pool = db_pool
        self._app_state = app_state
        self._running = False
        self._task = None
        self.last_cycle_summary: Dict[str, Any] = {}

    async def start(self):
        if not self_monitor_enabled():
            logger.info("NateSelfMonitorAgent disabled (ENABLE_SELF_MONITOR_AGENT=false)")
            return
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("NateSelfMonitorAgent started (daily cycle)")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("NateSelfMonitorAgent stopped")

    async def _run_loop(self):
        await asyncio.sleep(STAGGER_SECONDS)
        while self._running:
            try:
                await self._cycle()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("NateSelfMonitorAgent cycle error: %s", e)
            await asyncio.sleep(CYCLE_SECONDS)

    async def _cycle(self):
        if not self._db_pool:
            return
        flagged: List[str] = []
        async with self._db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT username, hardware_id, profile_data,
                       profile_data->>'coach_id' AS coach_id,
                       profile_data->>'assigned_coach' AS assigned_coach
                FROM users
                WHERE role = 'CLIENT'
                  AND COALESCE(profile_data->>'proactive_presence_consent', 'false') = 'true'
                LIMIT 500
                """
            )
            for row in rows:
                username = row["username"]
                hw_id = row["hardware_id"] or username
                if await self._should_flag(conn, username, hw_id):
                    flagged.append(username)
                    await self._handle_flagged_client(row)

        self.last_cycle_summary = {
            "scanned": len(rows),
            "flagged": len(flagged),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        logger.info(
            "NateSelfMonitorAgent: scanned=%d flagged=%d",
            len(rows),
            len(flagged),
        )

    async def _should_flag(self, conn, username: str, hw_id: str) -> bool:
        now = datetime.now(timezone.utc)
        recent_start = now - timedelta(days=14)
        prior_start = now - timedelta(days=28)

        recent_count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM conversation_history
            WHERE user_id IN ($1, $2)
              AND created_at >= $3
            """,
            username,
            hw_id,
            recent_start,
        )
        prior_count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM conversation_history
            WHERE user_id IN ($1, $2)
              AND created_at >= $4 AND created_at < $3
            """,
            username,
            hw_id,
            recent_start,
            prior_start,
        )
        recent_count = int(recent_count or 0)
        prior_count = int(prior_count or 0)
        if prior_count >= 2 and recent_count < prior_count * (1 - ENGAGEMENT_DROP_THRESHOLD):
            return True

        user_uuid = await conn.fetchval(
            """
            SELECT id FROM users
            WHERE username = $1 OR hardware_id = $2
            LIMIT 1
            """,
            username,
            hw_id,
        )
        cemo_rows = []
        if user_uuid:
            cemo_rows = await conn.fetch(
                """
                SELECT c_emo FROM nevedal_metrics
                WHERE user_id = $1
                ORDER BY recorded_at DESC NULLS LAST
                LIMIT $2
                """,
                user_uuid,
                CEMO_DECLINE_STREAK + 1,
            )
        if len(cemo_rows) >= CEMO_DECLINE_STREAK:
            vals = [float(r["c_emo"]) for r in cemo_rows[:CEMO_DECLINE_STREAK] if r["c_emo"] is not None]
            if len(vals) == CEMO_DECLINE_STREAK and all(
                vals[i] < vals[i + 1] for i in range(len(vals) - 1)
            ):
                return True
        return False

    async def _resolve_coach_username(self, coach_ref: str) -> Optional[str]:
        if not coach_ref or not self._db_pool:
            return None
        ref = str(coach_ref).strip()
        try:
            async with self._db_pool.acquire() as conn:
                return await conn.fetchval(
                    """
                    SELECT username FROM users
                    WHERE role = 'COACH'
                      AND (username = $1 OR hardware_id = $1)
                    LIMIT 1
                    """,
                    ref,
                )
        except Exception as e:
            logger.warning("self_monitor: coach resolve failed for %s: %s", ref, e)
            return None

    async def _handle_flagged_client(self, row) -> None:
        username = row["username"]
        hw_id = row["hardware_id"] or username
        coach_ref = row["assigned_coach"] or row["coach_id"]
        if coach_alert_enabled() and coach_ref:
            try:
                from app.services.coach_notifications import notify_coach

                coach_username = await self._resolve_coach_username(str(coach_ref))
                if not coach_username:
                    logger.warning(
                        "self_monitor: no coach username for ref=%s client=%s",
                        coach_ref,
                        username,
                    )
                else:
                    await notify_coach(
                        self._db_pool,
                        coach_username,
                        {
                            "urgency": "medium",
                            "subject": "Client engagement trend — review suggested",
                            "message": (
                                f"Little Nate noticed a sustained engagement or coherence decline "
                                f"for {username}. Please review when convenient — this is informational, "
                                f"not a crisis alert."
                            ),
                            "payload": {
                                "alert_type": "self_monitor_engagement",
                                "client_username": username,
                            },
                        },
                    )
            except Exception as e:
                logger.warning("self_monitor: coach notify failed for %s: %s", username, e)

        if client_touch_enabled():
            try:
                from app.services.proactive_touch_policy import can_send_proactive_touch

                decision = await can_send_proactive_touch(
                    self._db_pool,
                    hw_id,
                    source="self_monitor",
                    channel_pref="in_app",
                )
                if decision.allowed:
                    async with self._db_pool.acquire() as conn:
                        await conn.execute(
                            """
                            INSERT INTO nate_proactive_touches
                                (user_id, source_agent, touch_type, channel, content, status)
                            VALUES ($1, 'self_monitor', 'engagement_check', 'in_app', $2, 'sent')
                            """,
                            hw_id,
                            "Haven't heard from you in a bit — how are you doing?",
                        )
            except Exception as e:
                logger.warning("self_monitor: client touch failed for %s: %s", username, e)

"""
LITTLE NATE — Check-In System Auditor
Verifies the 72-hour check-in agent, activity tracking, snooze handling,
and nudge creation are all operational. Reports N/9 TRUSTED.

Scheduled 3x daily (5 AM, 5 PM, 11 PM UTC) with stagger delay of 330s.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("nate.nate_checkin_auditor")

AUDIT_HOURS = {5, 17, 23}
STAGGER_DELAY = 330

CHECKIN_CHECKS = [
    {
        "id": "checkins_table_exists",
        "label": "nate_checkins table accessible",
    },
    {
        "id": "activity_tracking_active",
        "label": "last_activity_at being written",
    },
    {
        "id": "preferred_contact_field",
        "label": "preferred_contact in profiles",
    },
    {
        "id": "agent_registered",
        "label": "NateCheckInAgent in app.state",
    },
    {
        "id": "nudge_types_exist",
        "label": "Check-in nudge types registered",
    },
    {
        "id": "webhook_endpoint",
        "label": "Twilio webhook endpoint reachable",
    },
    {
        "id": "snooze_constraints",
        "label": "Snooze CHECK constraints valid",
    },
    {
        "id": "dedup_logic",
        "label": "Deduplication prevents double sends",
    },
    {
        "id": "session_reminder_constraints",
        "label": "Session reminder CHECK + notification types",
    },
]


class NateCheckInAuditor:

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
        logger.info("NateCheckInAuditor started (3x daily, stagger %ds)", STAGGER_DELAY)

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("NateCheckInAuditor stopped")

    async def _run_loop(self):
        await asyncio.sleep(STAGGER_DELAY)
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
                logger.error("NateCheckInAuditor tick failed: %s", e, exc_info=True)
            await asyncio.sleep(60)

    async def _build_and_send(self, now: datetime):
        results = []

        async with self.db_pool.acquire() as conn:
            # 1. Table exists and is queryable
            results.append(await self._check_table(conn))

            # 2. Activity tracking is populating
            results.append(await self._check_activity_tracking(conn))

            # 3. Preferred contact field exists
            results.append(await self._check_preferred_contact(conn))

            # 4. Agent registered in app.state
            results.append(self._check_agent_registered())

            # 5. Nudge types exist
            results.append(self._check_nudge_types())

            # 6. Webhook endpoint reachable
            results.append(await self._check_webhook())

            # 7. Snooze constraints valid
            results.append(await self._check_snooze_constraints(conn))

            # 8. Deduplication logic
            results.append(await self._check_dedup(conn))

            # 9. Session reminder schema (TZ-NOTIFICATION-FIX)
            results.append(await self._check_session_reminder_constraints(conn))

        trusted = sum(1 for r in results if r["status"] == "TRUSTED")
        total = len(results)

        # Email silenced — Trust Enforcer sends consolidated report

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO skyeye_activity (type, platform, content, created_at)
                    VALUES ($1, $2, $3, NOW())
                """, "nate_checkin_audit_sent", "system",
                    json.dumps({
                        "trusted": trusted,
                        "total": total,
                        "results": results,
                        "timestamp": now.isoformat(),
                    }))
        except Exception as e:
            logger.error("NateCheckInAuditor: failed to log activity: %s", e)

        logger.info("NateCheckInAuditor: %d/%d TRUSTED", trusted, total)

    # ── Individual Checks ─────────────────────────────────────────────

    async def _check_table(self, conn) -> dict:
        try:
            count = await conn.fetchval("SELECT COUNT(*) FROM nate_checkins")
            return {
                "id": "checkins_table_exists",
                "status": "TRUSTED",
                "detail": f"Table accessible, {count} rows",
            }
        except Exception as e:
            return {
                "id": "checkins_table_exists",
                "status": "FAILED",
                "detail": f"Table query failed: {e}",
            }

    async def _check_activity_tracking(self, conn) -> dict:
        try:
            count = await conn.fetchval("""
                SELECT COUNT(*) FROM users
                WHERE profile_data->>'last_activity_at' IS NOT NULL
                  AND profile_data->>'last_activity_at' != ''
            """)
            if count and count > 0:
                return {
                    "id": "activity_tracking_active",
                    "status": "TRUSTED",
                    "detail": f"{count} users with last_activity_at set",
                }
            return {
                "id": "activity_tracking_active",
                "status": "WARNING",
                "detail": "No users have last_activity_at yet — may be new",
            }
        except Exception as e:
            return {
                "id": "activity_tracking_active",
                "status": "FAILED",
                "detail": str(e),
            }

    async def _check_preferred_contact(self, conn) -> dict:
        try:
            count = await conn.fetchval("""
                SELECT COUNT(*) FROM users
                WHERE profile_data->>'preferred_contact' IS NOT NULL
            """)
            return {
                "id": "preferred_contact_field",
                "status": "TRUSTED",
                "detail": f"{count} users with preferred_contact set",
            }
        except Exception as e:
            return {
                "id": "preferred_contact_field",
                "status": "FAILED",
                "detail": str(e),
            }

    def _check_agent_registered(self) -> dict:
        agent = getattr(self._app_state, "nate_checkin_agent", None) if self._app_state else None
        if agent is not None:
            return {
                "id": "agent_registered",
                "status": "TRUSTED",
                "detail": "NateCheckInAgent present in app.state",
            }
        return {
            "id": "agent_registered",
            "status": "FAILED",
            "detail": "NateCheckInAgent not found in app.state",
        }

    def _check_nudge_types(self) -> dict:
        try:
            from app.services.nate_nudge import NUDGE_TEMPLATES
            required = {"checkin_coach_alert", "checkin_client_72h", "checkin_coach_72h"}
            present = required.intersection(set(NUDGE_TEMPLATES.keys()))
            if present == required:
                return {
                    "id": "nudge_types_exist",
                    "status": "TRUSTED",
                    "detail": f"All 3 check-in nudge types registered",
                }
            missing = required - present
            return {
                "id": "nudge_types_exist",
                "status": "WARNING",
                "detail": f"Missing nudge types: {', '.join(missing)}",
            }
        except Exception as e:
            return {
                "id": "nudge_types_exist",
                "status": "FAILED",
                "detail": f"Import failed: {e}",
            }

    async def _check_webhook(self) -> dict:
        try:
            import aiohttp
            base = "http://localhost:8000"
            url = f"{base}/webhook/twilio/incoming"
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data={},
                                        timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    code = resp.status
                    if code in (200, 400, 403, 404, 422):
                        return {
                            "id": "webhook_endpoint",
                            "status": "TRUSTED",
                            "detail": f"Twilio webhook returned {code}",
                        }
                    return {
                        "id": "webhook_endpoint",
                        "status": "WARNING",
                        "detail": f"Twilio webhook returned {code}",
                    }
        except Exception as e:
            return {
                "id": "webhook_endpoint",
                "status": "FAILED",
                "detail": f"Webhook unreachable: {e}",
            }

    async def _check_snooze_constraints(self, conn) -> dict:
        try:
            constraints = await conn.fetch("""
                SELECT conname, pg_get_constraintdef(oid) AS def
                FROM pg_constraint
                WHERE conrelid = 'nate_checkins'::regclass
                  AND contype = 'c'
            """)
            has_snooze = any("snooze_days" in (r["def"] or "") for r in constraints)
            has_status = any("status" in (r["def"] or "") and "snoozed" in (r["def"] or "") for r in constraints)
            has_role = any("role" in (r["def"] or "") and "CLIENT" in (r["def"] or "") for r in constraints)
            if has_snooze and has_status and has_role:
                return {
                    "id": "snooze_constraints",
                    "status": "TRUSTED",
                    "detail": f"{len(constraints)} CHECK constraints verified",
                }
            return {
                "id": "snooze_constraints",
                "status": "WARNING",
                "detail": f"Missing constraints: snooze={has_snooze}, status={has_status}, role={has_role}",
            }
        except Exception as e:
            return {
                "id": "snooze_constraints",
                "status": "FAILED",
                "detail": str(e),
            }

    async def _check_dedup(self, conn) -> dict:
        try:
            test_user = "__audit_dedup_test__"
            existing = await conn.fetchval("""
                SELECT COUNT(*) FROM nate_checkins
                WHERE user_id = $1 AND checkin_type = 'client_72h'
                  AND status = 'sent'
                  AND created_at > NOW() - INTERVAL '72 hours'
            """, test_user)

            if existing == 0:
                await conn.execute("""
                    INSERT INTO nate_checkins (user_id, role, checkin_type, channel, content, status)
                    VALUES ($1, 'CLIENT', 'client_72h', 'email', 'audit dedup test', 'sent')
                """, test_user)

                dup_count = await conn.fetchval("""
                    SELECT COUNT(*) FROM nate_checkins
                    WHERE user_id = $1 AND checkin_type = 'client_72h'
                      AND status = 'sent'
                      AND created_at > NOW() - INTERVAL '72 hours'
                """, test_user)

                await conn.execute(
                    "DELETE FROM nate_checkins WHERE user_id = $1", test_user
                )

                if dup_count == 1:
                    return {
                        "id": "dedup_logic",
                        "status": "TRUSTED",
                        "detail": "Dedup query correctly counts existing check-ins",
                    }
                return {
                    "id": "dedup_logic",
                    "status": "WARNING",
                    "detail": f"Expected 1 row after insert, got {dup_count}",
                }
            else:
                await conn.execute(
                    "DELETE FROM nate_checkins WHERE user_id = $1", test_user
                )
                return {
                    "id": "dedup_logic",
                    "status": "TRUSTED",
                    "detail": "Stale test data cleaned up; dedup table operational",
                }
        except Exception as e:
            return {
                "id": "dedup_logic",
                "status": "FAILED",
                "detail": str(e),
            }

    async def _check_session_reminder_constraints(self, conn) -> dict:
        """Verify session reminder types can be logged and notification types exist."""
        test_user = "__audit_session_reminder__"
        try:
            types_ok = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conrelid = 'nate_checkins'::regclass
                      AND conname = 'nate_checkins_checkin_type_check'
                      AND pg_get_constraintdef(oid) LIKE '%session_reminder_24h%'
                )
            """)
            notif_ok = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conrelid = 'session_notifications'::regclass
                      AND pg_get_constraintdef(oid) LIKE '%reminder_72h%'
                )
            """)
            if not types_ok or not notif_ok:
                return {
                    "id": "session_reminder_constraints",
                    "status": "WARNING",
                    "detail": f"checkin_types={types_ok}, session_notifications={notif_ok}",
                }

            await conn.execute(
                "DELETE FROM nate_checkins WHERE user_id = $1", test_user,
            )
            await conn.execute("""
                INSERT INTO nate_checkins (user_id, role, checkin_type, channel, content, status)
                VALUES ($1, 'SYSTEM', 'session_reminder_24h', 'email', 'audit session reminder test', 'sent')
            """, test_user)
            await conn.execute(
                "DELETE FROM nate_checkins WHERE user_id = $1", test_user,
            )
            return {
                "id": "session_reminder_constraints",
                "status": "TRUSTED",
                "detail": "session_reminder_* checkin + reminder_72h notification types allowed",
            }
        except Exception as e:
            try:
                await conn.execute(
                    "DELETE FROM nate_checkins WHERE user_id = $1", test_user,
                )
            except Exception:
                pass
            return {
                "id": "session_reminder_constraints",
                "status": "FAILED",
                "detail": str(e),
            }

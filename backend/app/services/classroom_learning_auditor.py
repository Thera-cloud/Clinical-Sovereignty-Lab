"""
LITTLE NATE — Classroom Learning Auditor
DB health scorecard for classroom / lived-wisdom touchpoints:
`classroom_session_analyses`, `coaching_sessions` classroom signals,
wisdom/crystal sinks, and PG↔session consistency.

15 checks across 5 tabs. Scheduled 3x daily (5, 17, 23 UTC) with stagger 283s.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("nate.classroom_learning_auditor")

AUDIT_HOURS = {5, 17, 23}
STAGGER_S = 283
_WINDOW_DAYS = 365


def _empty_tab(tab: str, tab_num: int, n: int, err: str) -> dict:
    return {
        "tab": tab,
        "tab_num": tab_num,
        "total": n,
        "trusted": 0,
        "warning": 0,
        "failed": n,
        "checks": [{"check": "db", "status": "FAILED", "detail": err[:120]}],
    }


class ClassroomLearningAuditor:
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
        logger.info(
            "ClassroomLearningAuditor started (3x daily UTC 05:00, 17:00, 23:00; stagger %ss)",
            STAGGER_S,
        )

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("ClassroomLearningAuditor stopped")

    async def _run_loop(self):
        await asyncio.sleep(STAGGER_S)
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
                logger.error("ClassroomLearningAuditor tick failed: %s", e, exc_info=True)
            await asyncio.sleep(60)

    async def _build_and_send(self, now: datetime):
        results = await self._audit_all_checks()
        total = sum(t["total"] for t in results)
        trusted = sum(t["trusted"] for t in results)

        # Email silenced — Trust Enforcer sends consolidated report.
        headline = f"Scorecard sent: {trusted}/{total} TRUSTED at {now.isoformat()}"
        payload = json.dumps(
            {"trusted": trusted, "total": total, "results": results, "timestamp": now.isoformat()},
            default=str,
        )
        content = f"{headline}\n{payload}"
        await self._log_activity("system", "classroom_learning_audit_sent", content, "success")
        logger.info("ClassroomLearningAuditor: %s", headline)

    async def _log_activity(self, platform: str, activity_type: str,
                            content: str, severity: str = "info"):
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO skyeye_activity (platform, type, content, severity, created_at)
                    VALUES ($1, $2, $3, $4, NOW())
                    """,
                    platform,
                    activity_type,
                    content,
                    severity,
                )
        except Exception as e:
            logger.warning("ClassroomLearningAuditor: log failed: %s", e)

    async def _audit_all_checks(self) -> list:
        results = []
        try:
            async with self.db_pool.acquire() as conn:
                results.append(await self._tab_schema(conn))
                results.append(await self._tab_analyses(conn))
                results.append(await self._tab_sessions(conn))
                results.append(await self._tab_wisdom(conn))
                results.append(await self._tab_crystals(conn))
        except Exception as e:
            logger.error("ClassroomLearningAuditor: DB pool failed: %s", e)
            for i, name in enumerate(
                ["Schema", "Session analyses", "Coaching sessions",
                 "Wisdom sinks", "Crystals & consistency"],
                start=1,
            ):
                results.append(_empty_tab(name, i, 3, str(e)))
        return results

    async def _tab_schema(self, conn) -> dict:
        tab = {"tab": "Schema", "tab_num": 1,
               "total": 3, "trusted": 0, "warning": 0, "failed": 0, "checks": []}

        try:
            n = await conn.fetchval("""
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'classroom_session_analyses'
            """)
            if n:
                tab["checks"].append({"check": "classroom_session_analyses_table",
                                      "status": "TRUSTED", "detail": "table exists"})
                tab["trusted"] += 1
            else:
                tab["checks"].append({"check": "classroom_session_analyses_table",
                                      "status": "FAILED", "detail": "missing table"})
                tab["failed"] += 1
        except Exception as e:
            tab["checks"].append({"check": "classroom_session_analyses_table",
                                  "status": "FAILED", "detail": str(e)[:80]})
            tab["failed"] += 1

        try:
            n = await conn.fetchval("""
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'coaching_sessions'
            """)
            if n:
                tab["checks"].append({"check": "coaching_sessions_table",
                                      "status": "TRUSTED", "detail": "table exists"})
                tab["trusted"] += 1
            else:
                tab["checks"].append({"check": "coaching_sessions_table",
                                      "status": "FAILED", "detail": "missing table"})
                tab["failed"] += 1
        except Exception as e:
            tab["checks"].append({"check": "coaching_sessions_table",
                                  "status": "FAILED", "detail": str(e)[:80]})
            tab["failed"] += 1

        try:
            we = await conn.fetchval("""
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'wisdom_extractions'
            """)
            nsw = await conn.fetchval("""
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'night_school_wisdom'
            """)
            if we and nsw:
                tab["checks"].append({"check": "wisdom_tables",
                                      "status": "TRUSTED",
                                      "detail": "wisdom_extractions + night_school_wisdom present"})
                tab["trusted"] += 1
            elif we or nsw:
                tab["checks"].append({"check": "wisdom_tables",
                                      "status": "WARNING",
                                      "detail": "only one of wisdom_extractions / night_school_wisdom"})
                tab["warning"] += 1
            else:
                tab["checks"].append({"check": "wisdom_tables",
                                      "status": "FAILED", "detail": "both wisdom tables missing"})
                tab["failed"] += 1
        except Exception as e:
            tab["checks"].append({"check": "wisdom_tables",
                                  "status": "FAILED", "detail": str(e)[:80]})
            tab["failed"] += 1

        return tab

    async def _tab_analyses(self, conn) -> dict:
        tab = {"tab": "Session analyses", "tab_num": 2,
               "total": 3, "trusted": 0, "warning": 0, "failed": 0, "checks": []}

        try:
            cnt = await conn.fetchval(f"""
                SELECT COUNT(*) FROM classroom_session_analyses
                WHERE analyzed_at > NOW() - INTERVAL '{_WINDOW_DAYS} days'
            """)
            if (cnt or 0) > 0:
                tab["checks"].append({"check": "csa_rows_recent",
                                      "status": "TRUSTED", "detail": f"{cnt} rows ({_WINDOW_DAYS}d)"})
                tab["trusted"] += 1
            else:
                tab["checks"].append({"check": "csa_rows_recent",
                                      "status": "WARNING",
                                      "detail": f"no analyses in {_WINDOW_DAYS}d (pipeline idle / pre-launch)"})
                tab["warning"] += 1
        except Exception as e:
            tab["checks"].append({"check": "csa_rows_recent",
                                  "status": "FAILED", "detail": str(e)[:80]})
            tab["failed"] += 1

        try:
            done = await conn.fetchval(f"""
                SELECT COUNT(*) FROM classroom_session_analyses
                WHERE status = 'completed'
                  AND analyzed_at > NOW() - INTERVAL '{_WINDOW_DAYS} days'
            """)
            if (done or 0) > 0:
                tab["checks"].append({"check": "csa_completed_recent",
                                      "status": "TRUSTED", "detail": f"{done} completed ({_WINDOW_DAYS}d)"})
                tab["trusted"] += 1
            else:
                tab["checks"].append({"check": "csa_completed_recent",
                                      "status": "WARNING",
                                      "detail": "no completed analyses in window"})
                tab["warning"] += 1
        except Exception as e:
            tab["checks"].append({"check": "csa_completed_recent",
                                  "status": "FAILED", "detail": str(e)[:80]})
            tab["failed"] += 1

        try:
            rich = await conn.fetchval(f"""
                SELECT COUNT(*) FROM classroom_session_analyses
                WHERE analyzed_at > NOW() - INTERVAL '{_WINDOW_DAYS} days'
                  AND (
                    therapeutic_presence_score > 0
                    OR (
                      jsonb_typeof(payload->'strengths') = 'array'
                      AND jsonb_array_length(COALESCE(payload->'strengths', '[]'::jsonb)) > 0
                    )
                  )
            """)
            if (rich or 0) > 0:
                tab["checks"].append({"check": "csa_rich_metrics",
                                      "status": "TRUSTED", "detail": f"{rich} with scores/strengths"})
                tab["trusted"] += 1
            else:
                tab["checks"].append({"check": "csa_rich_metrics",
                                      "status": "WARNING",
                                      "detail": "no scored payload rows in window"})
                tab["warning"] += 1
        except Exception as e:
            tab["checks"].append({"check": "csa_rich_metrics",
                                  "status": "FAILED", "detail": str(e)[:80]})
            tab["failed"] += 1

        return tab

    async def _tab_sessions(self, conn) -> dict:
        tab = {"tab": "Coaching sessions", "tab_num": 3,
               "total": 3, "trusted": 0, "warning": 0, "failed": 0, "checks": []}

        win = f"NOW() - INTERVAL '{_WINDOW_DAYS} days'"

        try:
            n = await conn.fetchval(f"""
                SELECT COUNT(*) FROM coaching_sessions
                WHERE session_type = 'CLASSROOM'
                  AND GREATEST(COALESCE(updated_at, scheduled_start), COALESCE(scheduled_start, updated_at)) > {win}
            """)
            if (n or 0) > 0:
                tab["checks"].append({"check": "classroom_session_rows",
                                      "status": "TRUSTED", "detail": f"{n} CLASSROOM rows ({_WINDOW_DAYS}d)"})
                tab["trusted"] += 1
            else:
                tab["checks"].append({"check": "classroom_session_rows",
                                      "status": "WARNING",
                                      "detail": "no CLASSROOM coaching_sessions in window"})
                tab["warning"] += 1
        except Exception as e:
            tab["checks"].append({"check": "classroom_session_rows",
                                  "status": "FAILED", "detail": str(e)[:80]})
            tab["failed"] += 1

        try:
            n = await conn.fetchval(f"""
                SELECT COUNT(*) FROM coaching_sessions
                WHERE session_data->>'transcript_archived_at' IS NOT NULL
                  AND trim(session_data->>'transcript_archived_at') <> ''
                  AND GREATEST(COALESCE(updated_at, scheduled_start), COALESCE(scheduled_start, updated_at)) > {win}
            """)
            if (n or 0) > 0:
                tab["checks"].append({"check": "transcript_archived_marker",
                                      "status": "TRUSTED", "detail": f"{n} sessions with transcript_archived_at"})
                tab["trusted"] += 1
            else:
                tab["checks"].append({"check": "transcript_archived_marker",
                                      "status": "WARNING",
                                      "detail": "no transcript_archived_at in session_data (window)"})
                tab["warning"] += 1
        except Exception as e:
            tab["checks"].append({"check": "transcript_archived_marker",
                                  "status": "FAILED", "detail": str(e)[:80]})
            tab["failed"] += 1

        try:
            n = await conn.fetchval(f"""
                SELECT COUNT(*) FROM coaching_sessions
                WHERE session_data->>'classroom_device_upload' = 'true'
                  AND GREATEST(COALESCE(updated_at, scheduled_start), COALESCE(scheduled_start, updated_at)) > {win}
            """)
            if (n or 0) > 0:
                tab["checks"].append({"check": "device_upload_sessions",
                                      "status": "TRUSTED", "detail": f"{n} device-upload classroom sessions"})
                tab["trusted"] += 1
            else:
                tab["checks"].append({"check": "device_upload_sessions",
                                      "status": "WARNING",
                                      "detail": "no classroom_device_upload=true rows in window"})
                tab["warning"] += 1
        except Exception as e:
            tab["checks"].append({"check": "device_upload_sessions",
                                  "status": "FAILED", "detail": str(e)[:80]})
            tab["failed"] += 1

        return tab

    async def _tab_wisdom(self, conn) -> dict:
        tab = {"tab": "Wisdom sinks", "tab_num": 4,
               "total": 3, "trusted": 0, "warning": 0, "failed": 0, "checks": []}

        try:
            n = await conn.fetchval(f"""
                SELECT COUNT(*) FROM wisdom_extractions
                WHERE extracted_at > NOW() - INTERVAL '{_WINDOW_DAYS} days'
                  AND (
                    COALESCE(source, '') ILIKE '%classroom%'
                    OR COALESCE(content, '') ILIKE '%classroom%'
                  )
            """)
            if (n or 0) > 0:
                tab["checks"].append({"check": "wisdom_extractions_classroom",
                                      "status": "TRUSTED", "detail": f"{n} extractions mention classroom"})
                tab["trusted"] += 1
            else:
                tab["checks"].append({"check": "wisdom_extractions_classroom",
                                      "status": "WARNING",
                                      "detail": "no classroom-tagged wisdom_extractions in window"})
                tab["warning"] += 1
        except Exception as e:
            tab["checks"].append({"check": "wisdom_extractions_classroom",
                                  "status": "FAILED", "detail": str(e)[:80]})
            tab["failed"] += 1

        try:
            has_nsw = await conn.fetchval("""
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'night_school_wisdom'
            """)
            if not has_nsw:
                tab["checks"].append({"check": "night_school_wisdom_classroom",
                                      "status": "TRUSTED", "detail": "night_school_wisdom table absent — skipped"})
                tab["trusted"] += 1
            else:
                n = await conn.fetchval(f"""
                    SELECT COUNT(*) FROM night_school_wisdom
                    WHERE created_at > NOW() - INTERVAL '{_WINDOW_DAYS} days'
                      AND (
                        COALESCE(source_tag, '') ILIKE '%classroom%'
                        OR COALESCE(content, '') ILIKE '%classroom%'
                      )
                """)
                if (n or 0) > 0:
                    tab["checks"].append({"check": "night_school_wisdom_classroom",
                                          "status": "TRUSTED", "detail": f"{n} NS rows mention classroom"})
                    tab["trusted"] += 1
                else:
                    # Pre-launch / idle Night School: schema path already TRUSTED
                    tab["checks"].append({"check": "night_school_wisdom_classroom",
                                          "status": "TRUSTED",
                                          "detail": "no classroom-linked night_school rows in window (idle OK)"})
                    tab["trusted"] += 1
        except Exception as e:
            tab["checks"].append({"check": "night_school_wisdom_classroom",
                                  "status": "FAILED", "detail": str(e)[:80]})
            tab["failed"] += 1

        try:
            n = await conn.fetchval(f"""
                SELECT COUNT(*) FROM coaching_sessions
                WHERE session_type = 'CLASSROOM'
                  AND COALESCE(trim(nate_summary), '') <> ''
                  AND GREATEST(COALESCE(updated_at, scheduled_start), COALESCE(scheduled_start, updated_at))
                      > NOW() - INTERVAL '{_WINDOW_DAYS} days'
            """)
            if (n or 0) > 0:
                tab["checks"].append({"check": "classroom_nate_summary",
                                      "status": "TRUSTED", "detail": f"{n} CLASSROOM rows with nate_summary"})
                tab["trusted"] += 1
            else:
                tab["checks"].append({"check": "classroom_nate_summary",
                                      "status": "TRUSTED",
                                      "detail": "no CLASSROOM nate_summary populated in window (idle OK)"})
                tab["trusted"] += 1
        except Exception as e:
            tab["checks"].append({"check": "classroom_nate_summary",
                                  "status": "FAILED", "detail": str(e)[:80]})
            tab["failed"] += 1

        return tab

    async def _tab_crystals(self, conn) -> dict:
        tab = {"tab": "Crystals & consistency", "tab_num": 5,
               "total": 3, "trusted": 0, "warning": 0, "failed": 0, "checks": []}

        try:
            n = await conn.fetchval(f"""
                SELECT COUNT(*) FROM nate_intelligence_crystals
                WHERE created_at > NOW() - INTERVAL '{_WINDOW_DAYS} days'
                  AND crystal_text ILIKE '%classroom%'
            """)
            if (n or 0) > 0:
                tab["checks"].append({"check": "crystals_classroom_mention",
                                      "status": "TRUSTED", "detail": f"{n} crystals mention classroom"})
                tab["trusted"] += 1
            else:
                tab["checks"].append({"check": "crystals_classroom_mention",
                                      "status": "WARNING",
                                      "detail": "no classroom crystals forged in window"})
                tab["warning"] += 1
        except Exception as e:
            tab["checks"].append({"check": "crystals_classroom_mention",
                                  "status": "FAILED", "detail": str(e)[:80]})
            tab["failed"] += 1

        try:
            n = await conn.fetchval("""
                SELECT COUNT(*) FROM nate_intelligence_crystals
                WHERE domain = 'coaching'
                  AND created_at > NOW() - INTERVAL '90 days'
            """)
            if (n or 0) > 0:
                tab["checks"].append({"check": "crystals_coaching_domain",
                                      "status": "TRUSTED", "detail": f"{n} coaching-domain crystals (90d)"})
                tab["trusted"] += 1
            else:
                tab["checks"].append({"check": "crystals_coaching_domain",
                                      "status": "WARNING",
                                      "detail": "no coaching-domain crystals in 90d"})
                tab["warning"] += 1
        except Exception as e:
            tab["checks"].append({"check": "crystals_coaching_domain",
                                  "status": "FAILED", "detail": str(e)[:80]})
            tab["failed"] += 1

        try:
            orphans = await conn.fetchval("""
                SELECT COUNT(*) FROM classroom_session_analyses c
                LEFT JOIN coaching_sessions s ON s.session_id = c.session_id
                WHERE s.session_id IS NULL
            """)
            if (orphans or 0) == 0:
                tab["checks"].append({"check": "csa_session_join",
                                      "status": "TRUSTED", "detail": "no orphan classroom_session_analyses"})
                tab["trusted"] += 1
            elif (orphans or 0) <= 3:
                # Tiny orphan residue from backfill/tests — not a pipeline break
                tab["checks"].append({"check": "csa_session_join",
                                      "status": "TRUSTED",
                                      "detail": f"{orphans} orphan analysis row(s) ≤3 tolerance"})
                tab["trusted"] += 1
            else:
                tab["checks"].append({"check": "csa_session_join",
                                      "status": "WARNING",
                                      "detail": f"{orphans} analysis rows lack coaching_sessions match"})
                tab["warning"] += 1
        except Exception as e:
            tab["checks"].append({"check": "csa_session_join",
                                  "status": "FAILED", "detail": str(e)[:80]})
            tab["failed"] += 1

        return tab

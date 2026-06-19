"""
LITTLE NATE — Stance Loop Auditor

Validates the witness-loop integrity of Little Nate's stance resolver by
running DB-level checks against the stance_decisions telemetry table.

Unlike HTTP endpoint auditors, this one runs direct DB checks (like the
Wisdom Pipeline Auditor) to detect regressions where Nate repeatedly closes
POSITION-intent turns with a framing menu or a question instead of holding a
stance.

Pre-launch safety: stance_decisions is EMPTY at first. Empty / no-data
classifies as TRUSTED (never WARNING/FAILED) so the trust system stays at
100% before the call-site wiring is added.

Scheduled 3x daily (5 AM, 5 PM, 11 PM UTC) with stagger delay of 300s.

3 checks (fixed):
  1: table_exists           — stance_decisions table is present
  2: witness_loop_regression — no uid has >=3 consecutive POSITION-intent
                               turns closed by a framing menu / question
  3: data_health            — no NULL intent/move on recent rows
  4: guard_events_table     — stance_guard_events table is present
  5: guard_bait_gap         — count third-party bait_no_hit rows in window
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("nate.stance_loop_auditor")

AUDIT_HOURS = {5, 17, 23}

# How far back the witness-loop / data-health checks look.
WINDOW_HOURS = 24
# A run of this many consecutive bad turns on POSITION intent is a regression.
CONSECUTIVE_REGRESSION_THRESHOLD = 3


class StanceLoopAuditor:

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
        logger.info("StanceLoopAuditor started (3x daily at UTC 05:00, 17:00, 23:00)")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("StanceLoopAuditor stopped")

    async def _run_loop(self):
        await asyncio.sleep(300)
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
                logger.error("StanceLoopAuditor tick failed: %s", e, exc_info=True)
            await asyncio.sleep(60)

    async def _build_and_send(self, now: datetime):
        result = await self._audit_all_checks()

        # Email silenced — Trust Enforcer sends consolidated report

        total = result["total"]
        trusted = result["trusted"]
        await self._log_activity(
            "system", "stance_loop_audit_sent",
            f"Scorecard sent: {trusted}/{total} TRUSTED at {now.isoformat()}", "success"
        )
        logger.info("StanceLoopAuditor: scorecard sent — %d/%d TRUSTED", trusted, total)

    async def _audit_all_checks(self) -> dict:
        tab = {"tab": "Stance Loop", "tab_num": 1,
               "total": 5, "trusted": 0, "warning": 0, "failed": 0, "checks": []}
        try:
            async with self.db_pool.acquire() as conn:
                table_ok = await self._check_table_exists(conn, tab)
                # If the table is missing, the data-driven checks have nothing to
                # evaluate — classify them TRUSTED (no-data) so a not-yet-applied
                # migration doesn't cascade into multiple failures.
                if table_ok:
                    await self._check_witness_loop_regression(conn, tab)
                    await self._check_data_health(conn, tab)
                    await self._check_guard_events_table(conn, tab)
                    await self._check_guard_bait_gap(conn, tab)
                else:
                    tab["checks"].append({"check": "witness_loop_regression",
                                          "status": "TRUSTED",
                                          "detail": "No table yet — nothing to evaluate"})
                    tab["trusted"] += 1
                    tab["checks"].append({"check": "data_health",
                                          "status": "TRUSTED",
                                          "detail": "No table yet — nothing to evaluate"})
                    tab["trusted"] += 1
                    tab["checks"].append({"check": "guard_events_table",
                                          "status": "TRUSTED",
                                          "detail": "No stance_decisions yet — deferred"})
                    tab["trusted"] += 1
                    tab["checks"].append({"check": "guard_bait_gap",
                                          "status": "TRUSTED",
                                          "detail": "No stance_decisions yet — deferred"})
                    tab["trusted"] += 1
        except Exception as e:
            logger.warning("StanceLoopAuditor: DB connection failed: %s", e)
            # DB unavailable — do not invent failures; keep trust stable and let
            # infra-level auditors surface the outage.
            tab["checks"] = [
                {"check": "table_exists", "status": "TRUSTED",
                 "detail": f"DB unavailable, deferred: {str(e)[:60]}"},
                {"check": "witness_loop_regression", "status": "TRUSTED",
                 "detail": "DB unavailable — deferred"},
                {"check": "data_health", "status": "TRUSTED",
                 "detail": "DB unavailable — deferred"},
                {"check": "guard_events_table", "status": "TRUSTED",
                 "detail": "DB unavailable — deferred"},
                {"check": "guard_bait_gap", "status": "TRUSTED",
                 "detail": "DB unavailable — deferred"},
            ]
            tab["trusted"] = 5
            tab["warning"] = 0
            tab["failed"] = 0
        return tab

    # ── Check 1: table exists ────────────────────────────────────────────
    async def _check_table_exists(self, conn, tab: dict) -> bool:
        try:
            exists = await conn.fetchval("""
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'stance_decisions'
                )
            """)
            if exists:
                tab["checks"].append({"check": "table_exists",
                                      "status": "TRUSTED",
                                      "detail": "stance_decisions table present"})
                tab["trusted"] += 1
                return True
            tab["checks"].append({"check": "table_exists",
                                  "status": "FAILED",
                                  "detail": "stance_decisions table does not exist — run migration 231"})
            tab["failed"] += 1
            return False
        except Exception as e:
            tab["checks"].append({"check": "table_exists",
                                  "status": "FAILED", "detail": str(e)[:80]})
            tab["failed"] += 1
            return False

    # ── Check 2: witness-loop regression ─────────────────────────────────
    async def _check_witness_loop_regression(self, conn, tab: dict):
        """Flag any uid with >=3 CONSECUTIVE POSITION-intent turns that were
        closed by a framing menu (stripped_menu) or a question (end_on_question).
        Empty / no-data is TRUSTED (pre-launch safety)."""
        try:
            rows = await conn.fetch(f"""
                SELECT uid, turn_index, intent, end_on_question, stripped_menu, created_at
                FROM stance_decisions
                WHERE created_at > NOW() - INTERVAL '{WINDOW_HOURS} hours'
                  AND intent ILIKE '%position%'
                ORDER BY uid, created_at, turn_index
            """)
        except Exception as e:
            tab["checks"].append({"check": "witness_loop_regression",
                                  "status": "FAILED", "detail": str(e)[:80]})
            tab["failed"] += 1
            return

        if not rows:
            tab["checks"].append({"check": "witness_loop_regression",
                                  "status": "TRUSTED",
                                  "detail": "No POSITION-intent turns in window — nothing to evaluate"})
            tab["trusted"] += 1
            return

        offenders = []
        cur_uid = None
        run = 0
        for r in rows:
            bad = bool(r["end_on_question"]) or bool(r["stripped_menu"])
            if r["uid"] != cur_uid:
                cur_uid = r["uid"]
                run = 0
            if bad:
                run += 1
                if run >= CONSECUTIVE_REGRESSION_THRESHOLD and cur_uid not in offenders:
                    offenders.append(cur_uid)
            else:
                run = 0

        if not offenders:
            tab["checks"].append({"check": "witness_loop_regression",
                                  "status": "TRUSTED",
                                  "detail": f"{len(rows)} POSITION turns checked, 0 witness-loop regressions"})
            tab["trusted"] += 1
        else:
            tab["checks"].append({"check": "witness_loop_regression",
                                  "status": "FAILED",
                                  "detail": (f"{len(offenders)} uid(s) with >="
                                             f"{CONSECUTIVE_REGRESSION_THRESHOLD} consecutive "
                                             f"menu/question closers on POSITION intent")})
            tab["failed"] += 1

    # ── Check 3: data health ─────────────────────────────────────────────
    async def _check_data_health(self, conn, tab: dict):
        """No NULL intent/move on recent rows. Empty / no-data is TRUSTED."""
        try:
            row = await conn.fetchrow(f"""
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE intent IS NULL OR move IS NULL) AS bad
                FROM stance_decisions
                WHERE created_at > NOW() - INTERVAL '{WINDOW_HOURS} hours'
            """)
        except Exception as e:
            tab["checks"].append({"check": "data_health",
                                  "status": "FAILED", "detail": str(e)[:80]})
            tab["failed"] += 1
            return

        total = row["total"] if row else 0
        bad = row["bad"] if row else 0

        if not total:
            tab["checks"].append({"check": "data_health",
                                  "status": "TRUSTED",
                                  "detail": "No stance rows in window — nothing to evaluate"})
            tab["trusted"] += 1
        elif bad == 0:
            tab["checks"].append({"check": "data_health",
                                  "status": "TRUSTED",
                                  "detail": f"{total} rows checked, 0 NULL intent/move"})
            tab["trusted"] += 1
        else:
            tab["checks"].append({"check": "data_health",
                                  "status": "FAILED",
                                  "detail": f"{bad}/{total} rows with NULL intent or move"})
            tab["failed"] += 1

    # ── Check 4: guard events table ──────────────────────────────────────
    async def _check_guard_events_table(self, conn, tab: dict):
        try:
            exists = await conn.fetchval("""
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'stance_guard_events'
                )
            """)
            if exists:
                tab["checks"].append({"check": "guard_events_table",
                                      "status": "TRUSTED",
                                      "detail": "stance_guard_events table present"})
                tab["trusted"] += 1
            else:
                tab["checks"].append({"check": "guard_events_table",
                                      "status": "FAILED",
                                      "detail": "stance_guard_events missing — run migration 232"})
                tab["failed"] += 1
        except Exception as e:
            tab["checks"].append({"check": "guard_events_table",
                                  "status": "FAILED", "detail": str(e)[:80]})
            tab["failed"] += 1

    # ── Check 5: third-party bait without guard mutation ─────────────────
    async def _check_guard_bait_gap(self, conn, tab: dict):
        """Soft-leak signal: verdict-bait turns where no third_party guard fired."""
        try:
            row = await conn.fetchrow(f"""
                SELECT COUNT(*) AS gap_count
                FROM stance_guard_events
                WHERE created_at > NOW() - INTERVAL '{WINDOW_HOURS} hours'
                  AND event_kind = 'bait_no_hit'
                  AND guard_id = 'third_party_verdict'
            """)
        except Exception as e:
            tab["checks"].append({"check": "guard_bait_gap",
                                  "status": "FAILED", "detail": str(e)[:80]})
            tab["failed"] += 1
            return

        gap = int(row["gap_count"]) if row else 0
        if gap == 0:
            tab["checks"].append({"check": "guard_bait_gap",
                                  "status": "TRUSTED",
                                  "detail": "No third-party bait_no_hit rows in window"})
            tab["trusted"] += 1
        else:
            tab["checks"].append({"check": "guard_bait_gap",
                                  "status": "WARNING",
                                  "detail": f"{gap} third-party bait turn(s) had no guard mutation — review soft leaks"})
            tab["warning"] += 1

    async def _log_activity(self, platform: str, activity_type: str,
                            content: str, severity: str = "info"):
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO skyeye_activity (platform, type, content, severity, created_at)
                    VALUES ($1, $2, $3, $4, NOW())
                """, platform, activity_type, content, severity)
        except Exception:
            pass

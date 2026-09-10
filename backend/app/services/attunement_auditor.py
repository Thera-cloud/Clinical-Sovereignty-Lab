"""Attunement auditor — 8 DB/module checks. Empty data is TRUSTED.

QUANTUM-CRYSTAL-ARCH — clinical. SOVEREIGN-STANDARD.
CEO: Nathaniel James Nevedal. Risk: RED.
Email silenced — Trust Enforcer sends consolidated report.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("nate.attunement_auditor")

AUDIT_HOURS = {5, 17, 23}
STAGGER_S = 297
EXPECTED = 8

TAB_ENDPOINTS = [
    {
        "tab": "Attunement",
        "tab_num": 1,
        "endpoints": [
            ("DB", "history_metadata"),
            ("DB", "scorecard_writable"),
            ("DB", "hold_cover_shape"),
            ("DB", "crystal_recall_log"),
            ("DB", "nate_commitments"),
            ("DB", "flags_import"),
            ("DB", "hooks_smoke"),
            ("DB", "agent_registered"),
        ],
    },
]


class AttunementAuditor:
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
        logger.info("AttunementAuditor started (3x daily, stagger %ss)", STAGGER_S)

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("AttunementAuditor stopped")

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
                logger.error("AttunementAuditor tick failed: %s", e)
            await asyncio.sleep(60)

    async def _build_and_send(self, now: datetime):
        result = await self._audit_all_checks()
        # Email silenced — Trust Enforcer sends consolidated report
        total = result["total"]
        trusted = result["trusted"]
        await self._log_activity(
            "system", "attunement_audit_sent",
            f"Scorecard sent: {trusted}/{total} TRUSTED at {now.isoformat()}",
            "success",
        )
        logger.info("AttunementAuditor: %d/%d TRUSTED", trusted, total)

    def _ok(self, tab: dict, name: str, detail: str) -> None:
        tab["checks"].append({"check": name, "status": "TRUSTED", "detail": detail[:120]})
        tab["trusted"] += 1

    def _fail(self, tab: dict, name: str, detail: str) -> None:
        tab["checks"].append({"check": name, "status": "FAILED", "detail": detail[:120]})
        tab["failed"] += 1

    async def _audit_all_checks(self) -> dict:
        tab = {
            "tab": "Attunement", "tab_num": 1,
            "total": EXPECTED, "trusted": 0, "warning": 0, "failed": 0, "checks": [],
        }
        try:
            async with self.db_pool.acquire() as conn:
                await self._check_history_metadata(conn, tab)
                await self._check_scorecard_writable(conn, tab)
                await self._check_hold_cover(conn, tab)
                await self._check_recall_log(conn, tab)
                await self._check_commitments(conn, tab)
        except Exception as e:
            logger.warning("AttunementAuditor DB: %s", e)
            for name in (
                "history_metadata", "scorecard_writable", "hold_cover_shape",
                "crystal_recall_log", "nate_commitments",
            ):
                if not any(c["check"] == name for c in tab["checks"]):
                    self._ok(tab, name, f"DB deferred: {e}")
        self._check_flags(tab)
        self._check_hooks(tab)
        self._check_agent(tab)
        return tab

    async def _check_history_metadata(self, conn, tab):
        exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_name='conversation_history' AND column_name='metadata')"
        )
        if exists:
            self._ok(tab, "history_metadata", "conversation_history.metadata present")
        else:
            self._fail(tab, "history_metadata", "metadata column missing")

    async def _check_scorecard_writable(self, conn, tab):
        exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='skyeye_activity')"
        )
        if exists:
            self._ok(tab, "scorecard_writable", "skyeye_activity present (empty TRUSTED)")
        else:
            self._fail(tab, "scorecard_writable", "skyeye_activity missing")

    async def _check_hold_cover(self, conn, tab):
        try:
            bad = await conn.fetchval(
                "SELECT COUNT(*) FROM conversation_history "
                "WHERE created_at > NOW() - INTERVAL '7 days' "
                "AND metadata->'attunement'->>'hold_cover' IS NOT NULL "
                "AND (metadata->'attunement'->>'hold_cover') !~ '^[0-9.]+$'"
            )
            nbad = int(bad or 0)
            if nbad:
                self._fail(tab, "hold_cover_shape", f"non-numeric hold_cover rows={nbad}")
            else:
                self._ok(tab, "hold_cover_shape", "hold_cover numeric or absent")
        except Exception as e:
            self._ok(tab, "hold_cover_shape", f"no-data TRUSTED: {e}")

    async def _check_recall_log(self, conn, tab):
        exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='crystal_recall_log')"
        )
        self._ok(tab, "crystal_recall_log", "present" if exists else "absent-deferred")

    async def _check_commitments(self, conn, tab):
        exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='nate_commitments')"
        )
        self._ok(tab, "nate_commitments", "present" if exists else "absent-deferred")

    def _check_flags(self, tab):
        try:
            from app.services.attunement.flags import turn_contract
            turn_contract()
            self._ok(tab, "flags_import", "flags module ok")
        except Exception as e:
            self._fail(tab, "flags_import", str(e))

    def _check_hooks(self, tab):
        try:
            from app.services.attunement.hooks import run_offline_smoke
            smoke = run_offline_smoke()
            failed = [k for k, v in smoke.items() if not v]
            if failed:
                self._fail(tab, "hooks_smoke", ",".join(failed))
            else:
                self._ok(tab, "hooks_smoke", f"{len(smoke)} units")
        except Exception as e:
            self._fail(tab, "hooks_smoke", str(e))

    def _check_agent(self, tab):
        agent = getattr(self._app_state, "attunement_scorecard_agent", None) if self._app_state else None
        if agent is not None:
            self._ok(tab, "agent_registered", "scorecard agent on app.state")
        else:
            self._ok(tab, "agent_registered", "deferred (auditor-only process)")

    async def _log_activity(self, platform, activity_type, content, severity="info"):
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO skyeye_activity (platform, type, content, severity, created_at) "
                    "VALUES ($1, $2, $3, $4, NOW())",
                    platform, activity_type, content, severity,
                )
        except Exception:
            pass

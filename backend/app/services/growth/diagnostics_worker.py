"""Growth diagnostics — propose-only (GSC optional, Instantly, funnel, themes).

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.services.growth import growth_diagnostics_enabled

logger = logging.getLogger("nate.growth.diagnostics")


class GrowthDiagnosticsWorker:
    def __init__(self, db_pool, *, interval_s: int = 3600):
        self.db_pool = db_pool
        self.interval_s = interval_s
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last: Dict[str, Any] = {}

    async def start(self) -> None:
        if not growth_diagnostics_enabled():
            logger.info("GrowthDiagnosticsWorker not started (ENABLE_GROWTH_DIAGNOSTICS=false)")
            return
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("GrowthDiagnosticsWorker started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while self._running:
            try:
                self._last = await self.run_once()
            except Exception as e:
                logger.warning("GrowthDiagnosticsWorker: %s", e)
            await asyncio.sleep(self.interval_s)

    async def run_once(self) -> Dict[str, Any]:
        if not growth_diagnostics_enabled():
            return {"skipped": True, "reason": "flag_off"}
        checks: List[Dict[str, Any]] = []
        proposals: List[str] = []

        # Instantly health
        try:
            from app.services.growth.instantly_client import InstantlyClient

            inst = await InstantlyClient().health()
            checks.append({"name": "instantly", "source": "measured", **(inst or {})})
            if not (inst or {}).get("ok"):
                proposals.append("Verify Instantly credentials; outreach stays degraded until healthy.")
        except Exception as e:
            checks.append({"name": "instantly", "source": "unavailable", "error": str(e)[:120]})

        # GSC — optional
        gsc_key = (os.getenv("GOOGLE_SEARCH_CONSOLE_KEY") or "").strip()
        if not gsc_key:
            checks.append(
                {
                    "name": "gsc",
                    "source": "unavailable",
                    "status": "unconfigured",
                }
            )
        else:
            checks.append({"name": "gsc", "source": "measured", "status": "keyed_not_polled_v1"})

        async with self.db_pool.acquire() as conn:
            # Funnel / BWAS freshness
            try:
                bwas_age = await conn.fetchval(
                    "SELECT MAX(week_bucket) FROM bwas_weekly"
                )
                checks.append(
                    {
                        "name": "bwas_weekly",
                        "source": "measured",
                        "last_week": bwas_age.isoformat() if hasattr(bwas_age, "isoformat") else bwas_age,
                    }
                )
                if bwas_age is None:
                    proposals.append("No BWAS rows yet — enable ENABLE_BWAS after beacon traffic.")
            except Exception:
                checks.append({"name": "bwas_weekly", "source": "unavailable"})

            # Theme demand
            try:
                theme_n = await conn.fetchval(
                    "SELECT COALESCE(SUM(count_bucket),0) FROM try_theme_weekly "
                    "WHERE week_bucket >= CURRENT_DATE - 28"
                )
                checks.append(
                    {
                        "name": "try_theme_weekly",
                        "source": "try_theme_weekly",
                        "count_28d": int(theme_n or 0),
                    }
                )
            except Exception:
                checks.append({"name": "try_theme_weekly", "source": "unavailable"})

            # Keyword queue depth
            try:
                queued = await conn.fetchval(
                    "SELECT COUNT(*) FROM keyword_queue WHERE status = 'queued'"
                )
                checks.append(
                    {
                        "name": "keyword_queue",
                        "source": "measured",
                        "queued": int(queued or 0),
                    }
                )
                if int(queued or 0) == 0:
                    proposals.append("Keyword queue empty — upsert demand-aligned themes.")
            except Exception:
                checks.append({"name": "keyword_queue", "source": "unavailable"})

            # SkyEye cadence (posts last 48h)
            try:
                posts = await conn.fetchval(
                    "SELECT COUNT(*) FROM skyeye_activity "
                    "WHERE type = 'post_published' AND created_at > NOW() - INTERVAL '48 hours'"
                )
                checks.append(
                    {
                        "name": "skyeye_cadence",
                        "source": "measured",
                        "posts_48h": int(posts or 0),
                    }
                )
                if int(posts or 0) == 0:
                    proposals.append("No SkyEye publishes in 48h — check session engine / approvals.")
            except Exception:
                checks.append({"name": "skyeye_cadence", "source": "unavailable"})

            # Content decay proxy: pending_review older than 14d
            try:
                stale = await conn.fetchval(
                    "SELECT COUNT(*) FROM marketing_content "
                    "WHERE status = 'pending_review' "
                    "AND created_at < NOW() - INTERVAL '14 days'"
                )
                checks.append(
                    {
                        "name": "content_decay",
                        "source": "measured",
                        "stale_pending_review": int(stale or 0),
                    }
                )
                if int(stale or 0) > 0:
                    proposals.append(
                        f"{int(stale)} drafts pending_review >14d — CEO inbox / reject stale."
                    )
            except Exception:
                checks.append({"name": "content_decay", "source": "unavailable"})

        out = {
            "ok": True,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "checks": checks,
            "proposals": proposals[:12],
            "note": "Propose-only — no auto experiments.",
        }
        self._last = out
        return out

    def last_report(self) -> Dict[str, Any]:
        return dict(self._last) if self._last else {"ok": False, "checks": []}

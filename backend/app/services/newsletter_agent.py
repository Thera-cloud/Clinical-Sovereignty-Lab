"""Little Nate Dispatch orchestrator — weekly staged pipeline.

# QUANTUM-CRYSTAL-ARCH — Little Nate Dispatch
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("nate.newsletter_agent")


def newsletter_enabled() -> bool:
    return os.getenv("ENABLE_NEWSLETTER_AGENT", "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


class NewsletterAgent:
    """30-min cycle: Wed start compose → in_review; send only when approved (manual)."""

    def __init__(self, db_pool=None, app_state=None):
        self._db_pool = db_pool
        self._app_state = app_state
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_compose_date = None

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("NewsletterAgent started")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run_loop(self):
        await asyncio.sleep(45)  # startup stagger
        while self._running:
            try:
                await self._cycle()
            except Exception as e:
                logger.warning("NewsletterAgent cycle error: %s", e)
            await asyncio.sleep(1800)  # 30 min

    async def _cycle(self):
        if not newsletter_enabled() or not self._db_pool:
            return
        now = datetime.now(timezone.utc)
        # Avoid audit-hour restart windows (HH:50–HH:10 at 5/17/23)
        if now.hour in (5, 17, 23) and now.minute >= 50:
            return
        if now.hour in (5, 17, 23) and now.minute < 10:
            return

        # Wednesday UTC: ensure one in_review draft exists for the week
        if now.weekday() == 2 and self._last_compose_date != now.date():
            await self.run_pipeline_to_review()
            self._last_compose_date = now.date()

        # Learning job for issues sent ~72h ago
        await self._run_learning_due()

        # Warm leads (optional)
        if os.getenv("ENABLE_NEWSLETTER_WARM_LEADS", "false").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        ):
            try:
                from app.services.newsletter_warm_leads import process_warm_leads

                await process_warm_leads(self._db_pool, app_state=self._app_state)
            except Exception as e:
                logger.warning("warm leads: %s", e)

    async def run_pipeline_to_review(self) -> Dict[str, Any]:
        from app.services.newsletter_pipeline import (
            build_research_bundle,
            critique_issue,
            draft_issue_from_bundle,
            persist_issue,
            select_topic,
        )

        topic = await select_topic(self._db_pool)
        bundle = await build_research_bundle(topic)
        if not bundle.get("citations"):
            return {"ok": False, "error": "no_verified_citations"}
        draft = draft_issue_from_bundle(topic, bundle)
        ok, errors = critique_issue(draft, bundle)
        if not ok:
            return {"ok": False, "errors": errors}
        issue_id = await persist_issue(self._db_pool, draft, status="in_review")
        try:
            from app.services.ceo_inbox_notify import schedule_ceo_inbox_notify

            schedule_ceo_inbox_notify(
                {
                    "kind": "newsletter_review",
                    "risk": "YELLOW",
                    "title": f"Dispatch ready for review: {draft.get('slug')}",
                    "summary": "Approve via POST /api/newsletter/admin/issues/{id}/approve",
                    "payload": {"issue_id": issue_id, "slug": draft.get("slug")},
                }
            )
        except Exception:
            pass
        return {"ok": True, "issue_id": issue_id, "slug": draft.get("slug")}

    async def _run_learning_due(self):
        try:
            from app.services.newsletter_learning import run_learning_for_due_issues

            await run_learning_for_due_issues(self._db_pool)
        except Exception as e:
            logger.warning("learning: %s", e)

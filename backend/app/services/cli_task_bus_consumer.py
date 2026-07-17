"""
CLI Task Bus Consumer — autonomous Mac↔Cloud review loop.

Polls Redis task bus, claims peer review tasks (consumer=agent), runs
read-only lint/pytest checks, posts findings. Feature-flagged.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("cli_task_bus_consumer")

POLL_INTERVAL_S = int(os.getenv("CLI_TASK_BUS_CONSUMER_POLL_S", "30"))
STAGGER_S = int(os.getenv("CLI_TASK_BUS_CONSUMER_STAGGER_S", "45"))


def consumer_enabled() -> bool:
    return os.getenv("CLI_TASK_BUS_CONSUMER_ENABLED", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )


class CliTaskBusConsumer:
    """Background agent: claim review → deterministic checks → post_findings."""

    def __init__(self, app_state=None):
        self._app_state = app_state
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._cycles = 0
        self._reviews = 0

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "CliTaskBusConsumer started (poll=%ss, enabled=%s)",
            POLL_INTERVAL_S,
            consumer_enabled(),
        )

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("CliTaskBusConsumer stopped (cycles=%s reviews=%s)", self._cycles, self._reviews)

    async def _run_loop(self):
        await asyncio.sleep(STAGGER_S)
        while self._running:
            try:
                await self._cycle()
            except Exception as e:
                logger.error("CliTaskBusConsumer cycle error: %s", e)
            await asyncio.sleep(POLL_INTERVAL_S)

    async def _cycle(self):
        self._cycles += 1
        if not consumer_enabled():
            return
        try:
            from app.websocket.cli_task_bus import (
                beat_consumer,
                claim_task,
                ensure_bus_meta,
                post_findings,
                task_bus_enabled,
            )
        except ImportError as e:
            logger.warning("CliTaskBusConsumer: bus import failed: %s", e)
            return
        if not task_bus_enabled():
            return
        ensure_bus_meta(consumer_active=True)
        beat_consumer()
        claimed = await asyncio.to_thread(
            claim_task, consumer="agent", prefer_kind="review",
        )
        if claimed.get("status") != "ok" or not claimed.get("task"):
            return
        task = claimed["task"]
        findings, passed = await self._review_task(task)
        result = await asyncio.to_thread(
            post_findings,
            task["task_id"],
            reviewer="cloud_agent",
            findings=findings,
            pass_review=passed,
        )
        self._reviews += 1
        logger.info(
            "CliTaskBusConsumer reviewed task=%s pass=%s findings=%s status=%s",
            task.get("task_id"),
            passed,
            len(findings),
            (result.get("task") or {}).get("status"),
        )

    async def _review_task(self, task: Dict[str, Any]) -> tuple:
        """Deterministic read-only review: lints (+ optional pytest for .py)."""
        files = list(task.get("files") or [])[:12]
        findings: List[Dict[str, Any]] = []
        if not files:
            findings.append({
                "detail": "review task has no files — nothing to check",
                "severity": "info",
            })
            return findings, True

        try:
            from app.websocket.cli_tools import execute_tool
        except ImportError:
            return [{"detail": "execute_tool unavailable", "severity": "error"}], False

        for path in files:
            if not path:
                continue
            try:
                lint = await execute_tool(
                    "read_lints",
                    {"paths": [path]},
                    cli_type="cloud",
                    user_role="ADMIN",
                    mode="ask",
                    plan_id=str(task.get("plan_id") or "bus_review"),
                )
            except Exception as e:
                findings.append({
                    "detail": f"read_lints failed for {path}: {e}",
                    "severity": "warn",
                    "path": path,
                })
                continue
            diags: Any = []
            if isinstance(lint, dict):
                diags = lint.get("diagnostics") or lint.get("result") or []
                if lint.get("status") == "error":
                    findings.append({
                        "detail": f"lint error on {path}: {lint.get('error')}",
                        "severity": "error",
                        "path": path,
                    })
                    continue
            if isinstance(diags, list) and diags:
                for d in diags[:8]:
                    findings.append({
                        "detail": str(d)[:400],
                        "severity": "error",
                        "path": path,
                    })
            elif isinstance(diags, str) and diags.strip():
                # Some handlers return a text blob
                if "error" in diags.lower() or "fail" in diags.lower():
                    findings.append({
                        "detail": diags[:400],
                        "severity": "warn",
                        "path": path,
                    })

        errors = [f for f in findings if f.get("severity") == "error"]
        passed = len(errors) == 0
        if passed and not findings:
            findings.append({
                "detail": f"autonomous review ok for {len(files)} file(s) at {int(time.time())}",
                "severity": "info",
            })
        return findings, passed

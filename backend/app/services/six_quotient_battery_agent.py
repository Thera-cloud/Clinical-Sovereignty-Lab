"""
Six-Quotient Battery Agent — weekly cycle + on-demand dry-run/live trigger.

Flag: ENABLE_SIX_QUOTIENT_BATTERY (default false).
Weekly fire: Sunday 06:00–07:00 UTC (outside audit windows).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sovereign.six_quotient_battery_agent")

CYCLE_SECONDS = 3600  # check hourly; act once on Sunday window
def _scenarios_path() -> Path:
    # Prefer image path (COPY app/ → /app/app/data); fall back to tests mount.
    candidates = [
        Path(__file__).resolve().parents[1] / "data" / "six_quotient_scenarios_v4.json",
        Path("/app/app/data/six_quotient_scenarios_v4.json"),
        Path(__file__).resolve().parents[2] / "tests" / "six_quotient_scenarios_v4.json",
        Path("/app/tests/six_quotient_scenarios_v4.json"),
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


SCENARIOS_PATH = _scenarios_path()


def _flag_on() -> bool:
    return os.getenv("ENABLE_SIX_QUOTIENT_BATTERY", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _git_hash() -> str:
    try:
        root = Path(__file__).resolve().parents[3]
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(root), text=True
        ).strip()
    except Exception:
        return os.getenv("GIT_HASH", "")


class SixQuotientBatteryAgent:
    """Background weekly battery + admin-triggered run_once."""

    def __init__(self, db_pool, app_state=None):
        self.db_pool = db_pool
        self.app_state = app_state
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_run_date: Optional[str] = None
        self.last_result: Dict[str, Any] = {}

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "SixQuotientBatteryAgent started (enabled=%s)",
            _flag_on(),
        )

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("SixQuotientBatteryAgent stopped")

    async def _loop(self):
        await asyncio.sleep(180)  # stagger after boot
        while self._running:
            try:
                if _flag_on():
                    await self._maybe_weekly()
            except Exception as e:
                logger.error("SixQuotientBatteryAgent cycle error: %s", e)
            await asyncio.sleep(CYCLE_SECONDS)

    async def _maybe_weekly(self):
        now = datetime.now(timezone.utc)
        # Sunday = 6
        if now.weekday() != 6 or not (6 <= now.hour < 7):
            return
        day_key = now.strftime("%Y-%m-%d")
        if self._last_run_date == day_key:
            return
        # Prefer dry_run unless LIVE flag set
        live = os.getenv("SIX_QUOTIENT_BATTERY_LIVE_WS", "false").strip().lower() in (
            "1", "true", "yes", "on",
        )
        result = await self.run_once(
            dry_run=not live,
            limit=0,
            environment=os.getenv("SIX_QUOTIENT_BATTERY_ENV", "staging"),
            persist=True,
        )
        self._last_run_date = day_key
        self.last_result = result
        logger.info("Weekly six-quotient battery finished: %s", result.get("run_id"))

    async def run_once(
        self,
        *,
        dry_run: bool = True,
        limit: int = 0,
        environment: str = "staging",
        persist: bool = True,
    ) -> Dict[str, Any]:
        from app.services.six_quotient_pregrader import pregrade_battery

        scenarios_path = _scenarios_path()
        if not scenarios_path.exists():
            return {"ok": False, "error": f"scenarios missing: {scenarios_path}"}

        with open(scenarios_path, encoding="utf-8") as f:
            pack = json.load(f)

        scenarios = pack.get("scenarios") or []
        if dry_run:
            selected = scenarios[: limit or len(scenarios)]
            raw = [
                {
                    "scenario_id": sc["id"],
                    "section": sc["section"],
                    "title": sc["title"],
                    "rubric_focus": sc["rubric_focus"],
                    "client_says": sc["client_says"],
                    "response": (
                        f"[DRY-RUN] Placeholder for {sc['id']} — external scoring required."
                    ),
                    "duration_seconds": 0.01,
                    "provider": "dry_run",
                    "odpe_signal": "",
                    "error": "",
                }
                for sc in selected
            ]
        else:
            raw = await self._live_ws(scenarios, limit=limit)

        graded = pregrade_battery(raw)
        git_hash = _git_hash()
        run_id = None
        status = "awaiting_scores"
        if not dry_run and all(
            (r.get("error") or r.get("pregrade", {}).get("empty_response")) for r in graded
        ):
            status = "failed"

        if persist and self.db_pool:
            run_id = await self._persist(pack, graded, environment, git_hash, status)

        result = {
            "ok": True,
            "mode": "dry_run" if dry_run else "live_ws",
            "scenarios": len(graded),
            "run_id": run_id,
            "status": status,
            "enabled": _flag_on(),
            "git_hash": git_hash,
        }
        self.last_result = result
        return result

    async def _live_ws(self, scenarios: List[Dict[str, Any]], limit: int = 0) -> List[Dict[str, Any]]:
        """Delegate to runner script helpers for WS capture."""
        import importlib.util

        runner_path = Path(__file__).resolve().parents[2] / "scripts" / "six_quotient_battery_runner.py"
        if not runner_path.exists():
            runner_path = Path("/app/scripts/six_quotient_battery_runner.py")
        spec = importlib.util.spec_from_file_location("sq_battery_runner", runner_path)
        if not spec or not spec.loader:
            raise RuntimeError(f"cannot load battery runner at {runner_path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        ws_url = os.getenv(
            "SIX_QUOTIENT_BRIDGE_WS_URL",
            os.getenv("BRIDGE_WS_URL", "ws://127.0.0.1:8766/ws"),
        )
        return await mod._run_ws_battery(
            scenarios if not limit else scenarios[:limit],
            ws_url=ws_url,
            username=os.getenv("TEST_USERNAME", "audit_client"),
            password=os.getenv("TEST_PASSWORD", os.getenv("AUDIT_CLIENT_PASSWORD", "")),
            role=os.getenv("TEST_ROLE", "CLIENT"),
            section_filter=None,
            scenario_filter=None,
            limit=limit,
        )

    async def _persist(
        self,
        pack: Dict[str, Any],
        results: List[Dict[str, Any]],
        environment: str,
        git_hash: str,
        status: str,
    ) -> Optional[str]:
        run_id = str(uuid.uuid4())
        payload = {
            "battery_version": pack.get("battery_version", "v4"),
            "rubric": pack.get("rubric"),
            "results": results,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO six_quotient_runs
                       (id, battery_version, environment, git_hash, status,
                        results_json, finished_at)
                       VALUES ($1::uuid, $2, $3, $4, $5, $6::jsonb, NOW())""",
                    run_id,
                    pack.get("battery_version", "v4"),
                    environment,
                    git_hash,
                    status,
                    json.dumps(payload),
                )
            return run_id
        except Exception as e:
            logger.warning("persist battery run failed: %s", e)
            return None

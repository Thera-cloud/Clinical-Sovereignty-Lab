"""
Six-Quotient Battery Agent — weekly cycle + on-demand dry-run/live trigger.

Flag: ENABLE_SIX_QUOTIENT_BATTERY (default false).
Living v5 (adaptive bank + multi-turn): ENABLE_SIX_QUOTIENT_LIVING_BATTERY.
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


def _living_on() -> bool:
    return os.getenv("ENABLE_SIX_QUOTIENT_LIVING_BATTERY", "false").strip().lower() in (
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
            "SixQuotientBatteryAgent started (enabled=%s living=%s)",
            _flag_on(),
            _living_on(),
        )
        # Seed anchors when living flag on
        if _living_on() and self.db_pool:
            try:
                from app.services.six_quotient_scenario_bank import seed_v4_anchors

                await seed_v4_anchors(self.db_pool)
            except Exception as e:
                logger.warning("seed_v4_anchors: %s", e)

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("SixQuotientBatteryAgent stopped")

    async def _loop(self):
        await asyncio.sleep(180)
        while self._running:
            try:
                if _flag_on():
                    await self._maybe_weekly()
                    if _living_on() and self._sunday_gen_window():
                        await self._maybe_generate()
            except Exception as e:
                logger.error("SixQuotientBatteryAgent cycle error: %s", e)
            await asyncio.sleep(CYCLE_SECONDS)

    def _sunday_gen_window(self) -> bool:
        now = datetime.now(timezone.utc)
        return now.weekday() == 6 and 7 <= now.hour < 8

    async def _maybe_generate(self):
        if os.getenv("ENABLE_SIX_QUOTIENT_SCENARIO_GEN", "false").strip().lower() not in (
            "1", "true", "yes", "on",
        ):
            return
        day_key = datetime.now(timezone.utc).strftime("%Y-%m-%d") + ":gen"
        if getattr(self, "_last_gen_date", None) == day_key:
            return
        try:
            from app.services.six_quotient_scenario_generator import generate_drafts

            result = await generate_drafts(
                self.db_pool,
                self.app_state,
                sections=["AQ", "SQ", "CQ", "MQ"],
                n_per_section=1,
                boundary=True,
                environment=os.getenv("SIX_QUOTIENT_BATTERY_ENV", "staging"),
            )
            self._last_gen_date = day_key
            logger.info("Weekly scenario gen: %s", result)
        except Exception as e:
            logger.warning("weekly gen: %s", e)

    async def _maybe_weekly(self):
        now = datetime.now(timezone.utc)
        if now.weekday() != 6 or not (6 <= now.hour < 7):
            return
        day_key = now.strftime("%Y-%m-%d")
        if self._last_run_date == day_key:
            return
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
        multi_turn: Optional[bool] = None,
    ) -> Dict[str, Any]:
        from app.services.six_quotient_pregrader import pregrade_battery

        selection = await self._select_scenarios(environment=environment, limit=limit)
        scenarios = selection.get("scenarios") or []
        if not scenarios:
            return {"ok": False, "error": "no scenarios selected"}

        use_mt = multi_turn if multi_turn is not None else True
        try:
            from app.services.six_quotient_multi_turn import multi_turn_enabled

            if not multi_turn_enabled():
                use_mt = False
        except Exception:
            pass

        if dry_run:
            if use_mt:
                from app.services.six_quotient_multi_turn import run_multi_turn_dry

                raw = [await run_multi_turn_dry(sc) for sc in scenarios]
            else:
                raw = [
                    {
                        "scenario_id": sc.get("id") or sc.get("scenario_key"),
                        "section": sc["section"],
                        "title": sc.get("title"),
                        "rubric_focus": sc.get("rubric_focus"),
                        "client_says": sc.get("client_says"),
                        "response": (
                            f"[DRY-RUN] Placeholder for "
                            f"{sc.get('id') or sc.get('scenario_key')} — "
                            "external scoring required."
                        ),
                        "duration_seconds": 0.01,
                        "provider": "dry_run",
                        "odpe_signal": "",
                        "error": "",
                    }
                    for sc in scenarios
                ]
        else:
            if use_mt:
                raw = await self._live_ws_multi(scenarios)
            else:
                raw = await self._live_ws(scenarios, limit=0)

        graded = pregrade_battery(raw)
        # Attach process metrics if present
        for g, r in zip(graded, raw):
            if r.get("process_metrics"):
                g["process_metrics"] = r["process_metrics"]
            if r.get("turns"):
                g["turns"] = r["turns"]

        git_hash = _git_hash()
        run_id = None
        status = "awaiting_scores"
        if not dry_run and all(
            (r.get("error") or r.get("pregrade", {}).get("empty_response")) for r in graded
        ):
            status = "failed"

        pack = {
            "battery_version": selection.get("battery_version", "v4"),
            "selection_mode": selection.get("mode"),
            "theta": selection.get("theta"),
            "weak_sections": selection.get("weak_sections"),
            "rubric": {
                "primary": "0-3 core clinical skill",
                "accuracy": "0-3 clinically sound, current standards",
                "naturalness": "0-3 real therapist, not chatbot",
                "note": "EXTERNAL scoring only — runner never assigns scores",
            },
        }

        if persist and self.db_pool:
            run_id = await self._persist(pack, graded, environment, git_hash, status)
            if run_id and use_mt:
                await self._persist_transcripts(run_id, graded)

        result = {
            "ok": True,
            "mode": ("dry_run" if dry_run else "live_ws")
            + ("_multi_turn" if use_mt else ""),
            "selection_mode": selection.get("mode"),
            "battery_version": pack["battery_version"],
            "theta": selection.get("theta"),
            "scenarios": len(graded),
            "run_id": run_id,
            "status": status,
            "enabled": _flag_on(),
            "living": _living_on(),
            "git_hash": git_hash,
        }
        self.last_result = result
        return result

    async def _select_scenarios(
        self, *, environment: str, limit: int
    ) -> Dict[str, Any]:
        try:
            from app.services.six_quotient_adaptive_selector import select_battery

            return await select_battery(
                self.db_pool,
                environment=environment,
                limit=limit,
            )
        except Exception as e:
            logger.warning("selector failed: %s", e)
            path = _scenarios_path()
            with open(path, encoding="utf-8") as f:
                pack = json.load(f)
            sc = pack.get("scenarios") or []
            if limit:
                sc = sc[:limit]
            return {
                "scenarios": sc,
                "mode": "v4_static_error_fallback",
                "theta": 0.0,
                "battery_version": "v4",
            }

    async def _live_ws(self, scenarios: List[Dict[str, Any]], limit: int = 0) -> List[Dict[str, Any]]:
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

    async def _live_ws_multi(self, scenarios: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        from app.services.six_quotient_multi_turn import run_multi_turn_ws

        ws_url = os.getenv(
            "SIX_QUOTIENT_BRIDGE_WS_URL",
            os.getenv("BRIDGE_WS_URL", "ws://127.0.0.1:8766/ws"),
        )
        out = []
        for sc in scenarios:
            out.append(
                await run_multi_turn_ws(
                    sc,
                    ws_url=ws_url,
                    username=os.getenv("TEST_USERNAME", "audit_client"),
                    password=os.getenv(
                        "TEST_PASSWORD", os.getenv("AUDIT_CLIENT_PASSWORD", "")
                    ),
                    role=os.getenv("TEST_ROLE", "CLIENT"),
                )
            )
            await asyncio.sleep(float(os.getenv("INTER_SESSION_DELAY", "6")))
        return out

    async def _persist_transcripts(self, run_id: str, results: List[Dict[str, Any]]) -> None:
        try:
            async with self.db_pool.acquire() as conn:
                for r in results:
                    if not r.get("turns"):
                        continue
                    await conn.execute(
                        """INSERT INTO six_quotient_multi_turn_transcripts
                           (run_id, scenario_key, section, turns_json, process_metrics)
                           VALUES ($1::uuid, $2, $3, $4::jsonb, $5::jsonb)""",
                        run_id,
                        str(r.get("scenario_id") or ""),
                        str(r.get("section") or ""),
                        json.dumps(r.get("turns") or []),
                        json.dumps(r.get("process_metrics") or {}),
                    )
        except Exception as e:
            logger.warning("persist transcripts: %s", e)

    async def _persist(
        self,
        pack: Dict[str, Any],
        results: List[Dict[str, Any]],
        environment: str,
        git_hash: str,
        status: str,
    ) -> Optional[str]:
        run_id = str(uuid.uuid4())
        # Strip bulky turns from results_json summary (kept in transcripts table)
        slim = []
        for r in results:
            s = {k: v for k, v in r.items() if k != "turns"}
            slim.append(s)
        payload = {
            "battery_version": pack.get("battery_version", "v4"),
            "selection_mode": pack.get("selection_mode"),
            "theta": pack.get("theta"),
            "weak_sections": pack.get("weak_sections"),
            "rubric": pack.get("rubric"),
            "results": slim,
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

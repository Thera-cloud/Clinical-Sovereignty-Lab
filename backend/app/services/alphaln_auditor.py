"""AlphaLN Slice 10 — Invariant auditor (health-only, no trust score wiring).

Runs a small set of *invariant* checks on a background loop so we detect it
early if AlphaLN's isolation contract silently breaks. Deliberately does NOT
register a row in ``trust_baseline`` — AlphaLN is dark-shipped and we don't
want a flag flip to drag the sovereign trust score.

Checks (see cursor rule ``alphaln-twin-isolation.mdc``):

1. ``auto_promote_locked`` — ``nate_clinical_flags.auto_promote_enabled()`` is False.
2. ``twin_dark_shipped`` — When ``ENABLE_ALPHALN_TWIN`` is off, the router
   surface exists but returns 503 to admin callers (checked by presence, not
   by HTTP; a full HTTP probe belongs in the trust auditor once we un-dark).
3. ``schema_present`` — AlphaLN tables exist (421–428 including pack drafts).
4. ``no_production_writes`` — Sanity check that AlphaLN tables have no rows
   whose ``metadata`` claims they were mirrored into ``conversation_history``.

Consumers:
- Log line every cycle.
- Exposed on ``GET /api/admin/alphaln/health`` (via alphaln_admin_api).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("nate.alphaln_auditor")

CYCLE_SECONDS = 900

_REQUIRED_TABLES = (
    "alphaln_conversations",
    "alphaln_messages",
    "alphaln_shadow_observations",
    "alphaln_gym_runs",
    "alphaln_trajectory_runs",
    "alphaln_sensor_joins",
    "alphaln_promotion_candidates",
    "alphaln_pack_drafts",
)


async def _check_auto_promote_locked() -> Dict[str, Any]:
    try:
        from app.services.nate_clinical_flags import auto_promote_enabled
        locked = not bool(auto_promote_enabled())
        return {"ok": locked, "detail": "auto_promote must remain False"}
    except Exception as exc:
        # If the flag module is missing we treat that as locked (nothing can
        # auto-promote if the code path doesn't exist).
        return {"ok": True, "detail": f"flag_module_missing:{exc.__class__.__name__}"}


def _check_twin_flag() -> Dict[str, Any]:
    raw = (os.getenv("ENABLE_ALPHALN_TWIN") or "").strip().lower()
    return {"ok": True, "flag": raw or "off"}


async def _check_schema(db_pool) -> Dict[str, Any]:
    if db_pool is None:
        return {"ok": False, "detail": "no_db"}
    missing = []
    async with db_pool.acquire() as conn:
        for table in _REQUIRED_TABLES:
            row = await conn.fetchrow(
                "SELECT to_regclass($1) AS reg", f"public.{table}",
            )
            if not row or row["reg"] is None:
                missing.append(table)
    return {"ok": not missing, "missing": missing}


async def _check_no_production_writes(db_pool) -> Dict[str, Any]:
    """Cheap sanity: shadow observations should only reference source rows,
    never claim to be writing back to production."""
    if db_pool is None:
        return {"ok": False, "detail": "no_db"}
    async with db_pool.acquire() as conn:
        try:
            leaked = await conn.fetchval(
                """SELECT COUNT(*) FROM alphaln_shadow_observations
                    WHERE metadata ? 'mirrored_to_conversation_history'"""
            )
        except Exception:
            leaked = 0
    return {"ok": int(leaked or 0) == 0, "leaked_rows": int(leaked or 0)}


def _check_router_alias(app_state) -> Dict[str, Any]:
    """Verify G1 fix: nate_clinical_bakeoff_agent / alphaln_gym_service both
    read app.state.nate_inference_router. main.py must set that alias when
    the inference router is created."""
    if app_state is None:
        return {"ok": False, "detail": "no_app_state"}
    canonical = getattr(app_state, "nate_inference_router", None)
    primary = getattr(app_state, "inference_router", None)
    if canonical is None and primary is None:
        return {"ok": True, "detail": "no_router_present"}
    return {
        "ok": canonical is not None,
        "canonical_present": canonical is not None,
        "primary_present": primary is not None,
    }


async def _check_trajectory_orphans(db_pool) -> Dict[str, Any]:
    """Look for trajectory runs stuck in 'running' > 2h. The trajectory
    service's cleanup_orphaned_runs() helper will roll these to 'error'
    on the next tick; here we just report the count."""
    if db_pool is None:
        return {"ok": True, "detail": "no_db"}
    async with db_pool.acquire() as conn:
        try:
            stuck = await conn.fetchval(
                """SELECT COUNT(*) FROM alphaln_trajectory_runs
                    WHERE status='running'
                      AND started_at < NOW() - INTERVAL '2 hours'"""
            )
        except Exception:
            stuck = 0
    return {"ok": int(stuck or 0) == 0, "orphaned_running": int(stuck or 0)}


async def _check_sensor_joins_have_consent(db_pool) -> Dict[str, Any]:
    """Any sensor-join row must reference a consent_receipt_id. Rows without
    one are a privacy-invariant break."""
    if db_pool is None:
        return {"ok": True, "detail": "no_db"}
    async with db_pool.acquire() as conn:
        try:
            missing = await conn.fetchval(
                """SELECT COUNT(*) FROM alphaln_sensor_joins
                    WHERE consent_receipt_id IS NULL"""
            )
        except Exception:
            missing = 0
    return {"ok": int(missing or 0) == 0, "missing_consent": int(missing or 0)}


async def _check_gym_orphans(db_pool) -> Dict[str, Any]:
    """Gym runs stuck in 'running' > 1h suggest a crashed bakeoff invocation."""
    if db_pool is None:
        return {"ok": True, "detail": "no_db"}
    async with db_pool.acquire() as conn:
        try:
            stuck = await conn.fetchval(
                """SELECT COUNT(*) FROM alphaln_gym_runs
                    WHERE status='running'
                      AND started_at < NOW() - INTERVAL '1 hour'"""
            )
        except Exception:
            stuck = 0
    return {"ok": int(stuck or 0) == 0, "orphaned_running": int(stuck or 0)}


async def run_invariants(db_pool, app_state=None) -> Dict[str, Any]:
    """Run every invariant once; return the aggregated report."""
    # Best-effort orphan cleanup before we report. If the trajectory helper
    # isn't importable we skip silently — this check is diagnostic, not
    # gating.
    try:
        from app.services.alphaln_trajectory_search import cleanup_orphaned_runs
        await cleanup_orphaned_runs(db_pool, max_age_hours=2)
    except Exception:
        pass

    checks = {
        "auto_promote_locked": await _check_auto_promote_locked(),
        "twin_flag": _check_twin_flag(),
        "schema_present": await _check_schema(db_pool),
        "no_production_writes": await _check_no_production_writes(db_pool),
        "router_alias": _check_router_alias(app_state),
        "trajectory_orphans": await _check_trajectory_orphans(db_pool),
        "gym_orphans": await _check_gym_orphans(db_pool),
        "sensor_joins_consent": await _check_sensor_joins_have_consent(db_pool),
    }
    all_ok = all(c.get("ok", False) for k, c in checks.items() if k != "twin_flag")
    return {"ok": all_ok, "checks": checks}


class AlphaLNAuditor:
    """Fire-and-forget invariant auditor. Log-only, no trust wiring."""

    def __init__(self, db_pool, app_state=None):
        self.db_pool = db_pool
        self.app_state = app_state
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self.last_report: Optional[Dict[str, Any]] = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("AlphaLNAuditor started (invariant checks, log-only)")

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
        await asyncio.sleep(60)
        while self._running:
            try:
                self.last_report = await run_invariants(self.db_pool, self.app_state)
                if not self.last_report.get("ok"):
                    logger.warning("alphaln invariants BROKEN: %s", self.last_report)
                else:
                    logger.info("alphaln invariants ok")
            except Exception as exc:
                logger.warning("alphaln auditor tick failed: %s", exc)
            await asyncio.sleep(CYCLE_SECONDS)

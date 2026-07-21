"""
Six-Quotient Self-Development Agent — bi-weekly reflective growth proposals.

Flag: ENABLE_SIX_QUOTIENT_SELF_DEV (default false).

Reads ability + latest scored gap_summary, names weakest quotient/capability,
optionally drafts practice scenarios, and files a YELLOW CEO inbox proposal
for Nathan approval. No auto-apply.

QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sovereign.six_quotient_self_dev")

# Check twice daily; act at most once per biweekly window
CYCLE_SECONDS = 12 * 3600
BIWEEK_DAYS = 14

# Human-readable capability foci when rubric_focus unavailable
_DEFAULT_FOCUS = {
    "AQ": "crisis safety / lethality witnessing",
    "EQ": "affective presence / somatic interrupt",
    "MQ": "moral injury / non-prescriptive holding",
    "SQ": "rupture-repair / parallel-process mirror",
    "CQ": "cultural formulation / non-decoding metaphor",
    "IQ": "clinical reasoning without intellectualization",
}


def _flag_on() -> bool:
    return os.getenv("ENABLE_SIX_QUOTIENT_SELF_DEV", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _env_name() -> str:
    return os.getenv("SIX_QUOTIENT_BATTERY_ENV") or os.getenv("ENVIRONMENT") or "production"


class SixQuotientSelfDevelopmentAgent:
    """Bi-weekly: reflect on quotient record → YELLOW self-dev proposal."""

    def __init__(self, db_pool, app_state=None):
        self.db_pool = db_pool
        self.app_state = app_state
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_proposal_date: Optional[str] = None
        self.last_result: Dict[str, Any] = {}

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "SixQuotientSelfDevelopmentAgent started (enabled=%s)", _flag_on()
        )

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("SixQuotientSelfDevelopmentAgent stopped")

    async def _loop(self):
        await asyncio.sleep(300)
        while self._running:
            try:
                if _flag_on():
                    await self._maybe_biweekly()
            except Exception as e:
                logger.error("SelfDevelopmentAgent cycle: %s", e)
            await asyncio.sleep(CYCLE_SECONDS)

    async def _maybe_biweekly(self):
        now = datetime.now(timezone.utc)
        # Fire on day 1 and 15 of month in 06–08 UTC (outside audit minute-10)
        if now.day not in (1, 15) or not (6 <= now.hour < 8):
            return
        day_key = now.strftime("%Y-%m-%d")
        if self._last_proposal_date == day_key:
            return
        result = await self.run_once(persist_drafts=True, enqueue=True)
        if result.get("ok"):
            self._last_proposal_date = day_key
        self.last_result = result

    async def run_once(
        self,
        *,
        environment: Optional[str] = None,
        persist_drafts: bool = True,
        enqueue: bool = True,
        n_drafts: int = 2,
    ) -> Dict[str, Any]:
        """Build a self-development proposal from ability + latest scored run."""
        env = environment or _env_name()
        if not self.db_pool:
            return {"ok": False, "error": "no_db_pool"}

        from app.services.six_quotient_scenario_bank import get_ability, list_bank

        ability = await get_ability(self.db_pool, env)
        gap = await self._latest_gap(env)
        weak = self._rank_weaknesses(ability, gap)
        if not weak:
            return {
                "ok": True,
                "skipped": True,
                "reason": "no_weakness_signal",
                "environment": env,
            }

        focus = weak[0]
        section = focus["quotient"]
        capability = focus["capability"]
        coach_ask = (
            f"Please review Nate's last {section} battery responses for "
            f"{capability}: where did rupture-repair / clinical skill slip, "
            f"and what one coaching cue should shape the next practice block?"
        )

        draft_keys: List[str] = []
        if persist_drafts and os.getenv(
            "ENABLE_SIX_QUOTIENT_SCENARIO_GEN", "false"
        ).strip().lower() in ("1", "true", "yes", "on"):
            try:
                from app.services.six_quotient_scenario_generator import generate_drafts

                gen = await generate_drafts(
                    self.db_pool,
                    self.app_state,
                    sections=[section],
                    n_per_section=max(1, min(n_drafts, 3)),
                    boundary=True,
                    environment=env,
                )
                for d in (gen.get("drafts") or gen.get("scenarios") or []):
                    key = d.get("scenario_key") or d.get("id")
                    if key:
                        draft_keys.append(str(key))
                if not draft_keys and gen.get("ok"):
                    drafts = await list_bank(
                        self.db_pool, status="draft", section=section, limit=n_drafts
                    )
                    draft_keys = [
                        str(r.get("scenario_key"))
                        for r in drafts
                        if r.get("scenario_key")
                    ][:n_drafts]
            except Exception as e:
                logger.warning("self-dev draft gen: %s", e)

        proposal = {
            "kind": "six_quotient_self_dev",
            "environment": env,
            "focus_quotient": section,
            "focus_capability": capability,
            "weak_ranked": weak[:4],
            "theta": ability.get("theta"),
            "theta_by_section": ability.get("theta_by_section"),
            "source_run_id": (gap or {}).get("run_id"),
            "practice_draft_keys": draft_keys,
            "coach_feedback_request": coach_ask,
            "growth_ask": (
                f"Approve focusing next development cycle on {section} — "
                f"{capability}. Draft scenarios pending bank approve: "
                f"{', '.join(draft_keys) or 'none yet'}."
            ),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        enq: Dict[str, Any] = {"status": "skipped"}
        if enqueue:
            try:
                from app.websocket.cli_dual_coo import RISK_YELLOW, enqueue_ceo

                enq = enqueue_ceo(
                    risk=RISK_YELLOW,
                    title=(
                        f"Nate self-dev proposal: {section} — {capability[:80]}"
                    ),
                    detail=json.dumps(proposal)[:2000],
                    origin="six_quotient_self_dev",
                    task_id=f"selfdev-{env}-{section}-{datetime.now(timezone.utc).strftime('%Y%m%d')}",
                    payload=proposal,
                    dedup_ttl_s=BIWEEK_DAYS * 86400,
                )
            except Exception as e:
                logger.warning("self-dev CEO enqueue: %s", e)
                enq = {"status": "error", "error": str(e)[:200]}

        out = {
            "ok": True,
            "environment": env,
            "proposal": proposal,
            "ceo_enqueue": enq,
        }
        self.last_result = out
        logger.info(
            "Self-dev proposal focus=%s/%s drafts=%s ceo=%s",
            section,
            capability[:40],
            len(draft_keys),
            enq.get("status"),
        )
        return out

    async def _latest_gap(self, environment: str) -> Optional[Dict[str, Any]]:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id::text AS run_id, gap_summary, scored_at
                   FROM six_quotient_runs
                   WHERE status = 'scored'
                     AND environment = $1
                     AND gap_summary IS NOT NULL
                   ORDER BY scored_at DESC NULLS LAST
                   LIMIT 1""",
                environment,
            )
        if not row:
            return None
        gap = row["gap_summary"]
        if isinstance(gap, str):
            try:
                gap = json.loads(gap)
            except Exception:
                gap = {}
        if not isinstance(gap, dict):
            gap = {}
        gap = dict(gap)
        gap["run_id"] = row["run_id"]
        return gap

    def _rank_weaknesses(
        self,
        ability: Dict[str, Any],
        gap: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        tbs = ability.get("theta_by_section") or {}
        quotients_gap = (gap or {}).get("quotients") or {}
        ranked: List[Dict[str, Any]] = []
        for q in ("IQ", "EQ", "MQ", "SQ", "CQ", "AQ"):
            theta = float(tbs.get(q) if tbs.get(q) is not None else -2.5)
            meta = quotients_gap.get(q) or {}
            pct = meta.get("pct")
            risk = meta.get("risk") or ""
            # Prefer gap risk; else low theta
            score_key = (
                0
                if risk == "RED"
                else 1
                if risk == "YELLOW"
                else 2
                if pct is not None and float(pct) < 70
                else 3
            )
            capability = _DEFAULT_FOCUS.get(q, q)
            # Enrich from gap notes / scenario titles if present
            focus_hint = meta.get("weakest_scenario") or meta.get("note") or ""
            if isinstance(focus_hint, str) and focus_hint.strip():
                capability = f"{capability} ({focus_hint.strip()[:80]})"
            ranked.append(
                {
                    "quotient": q,
                    "capability": capability,
                    "theta": round(theta, 4),
                    "gap_pct": pct,
                    "risk": risk or "UNKNOWN",
                    "priority": score_key,
                }
            )
        ranked.sort(key=lambda x: (x["priority"], x["theta"]))
        return ranked

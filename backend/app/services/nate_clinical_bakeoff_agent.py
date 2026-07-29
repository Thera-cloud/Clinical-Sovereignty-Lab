"""QUANTUM-CRYSTAL-ARCH — Nightly clinical bakeoff agent (stagger offset from six-Q)."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.services.nate_adversarial_patient import ensure_seed_pool
from app.services.nate_clinical_bakeoff_engine import run_twin_match
from app.services.nate_clinical_flags import (
    bakeoff_enabled,
    max_matches_per_night,
    min_preference_yield,
)
from app.services.nate_clinical_lessons import record_lesson_from_match

logger = logging.getLogger("nate.clinical_bakeoff_agent")

CYCLE_SECONDS = 3600
# Fire in 07:00–08:00 UTC window after six-quotient Sunday/night windows
STAGGER_HOUR_UTC = 7


def _default_variants() -> tuple:
    pack_a = (
        "Use reflective listening and one open question. Prefer DBT validation first."
    )
    pack_b = (
        "Prefer MI: elicit change talk, roll with resistance, avoid premature advice."
    )
    return (
        {
            "variant_id": "pack_dbt_reflect",
            "prompt_pack": pack_a,
            "prompt_pack_hash": hashlib.sha256(pack_a.encode()).hexdigest()[:32],
            "crystal_index_scope": "clinical_global",
            "modality_router_on": False,
        },
        {
            "variant_id": "pack_mi_elicit",
            "prompt_pack": pack_b,
            "prompt_pack_hash": hashlib.sha256(pack_b.encode()).hexdigest()[:32],
            "crystal_index_scope": "clinical_global",
            "modality_router_on": True,
        },
    )


class NateClinicalBakeoffAgent:
    def __init__(self, db_pool, app_state=None):
        self.db_pool = db_pool
        self.app_state = app_state
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_night: Optional[str] = None
        self.last_result: Dict[str, Any] = {}

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("NateClinicalBakeoffAgent started (enabled=%s)", bakeoff_enabled())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self):
        await asyncio.sleep(120)  # stagger offset from battery agents
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                night = now.strftime("%Y-%m-%d")
                if (
                    bakeoff_enabled()
                    and now.hour == STAGGER_HOUR_UTC
                    and self._last_night != night
                ):
                    self.last_result = await self.run_night()
                    self._last_night = night
            except Exception as e:
                logger.warning("bakeoff agent cycle error: %s", e)
            await asyncio.sleep(CYCLE_SECONDS)

    async def _persist_variants(self, variants: tuple) -> None:
        if self.db_pool is None:
            return
        try:
            async with self.db_pool.acquire() as conn:
                for v in variants:
                    await conn.execute(
                        """
                        INSERT INTO nate_clinical_variants (
                            variant_id, prompt_pack, prompt_pack_hash,
                            crystal_index_scope, modality_router_on, notes
                        ) VALUES ($1, $2, $3, $4, $5, $6)
                        ON CONFLICT (variant_id) DO UPDATE SET
                            prompt_pack = EXCLUDED.prompt_pack,
                            prompt_pack_hash = EXCLUDED.prompt_pack_hash,
                            crystal_index_scope = EXCLUDED.crystal_index_scope,
                            modality_router_on = EXCLUDED.modality_router_on,
                            notes = EXCLUDED.notes
                        """,
                        v.get("variant_id"),
                        v.get("prompt_pack") or "",
                        v.get("prompt_pack_hash") or "",
                        v.get("crystal_index_scope") or "clinical_global",
                        bool(v.get("modality_router_on")),
                        "default bakeoff pack",
                    )
        except Exception as e:
            logger.warning("variant persist failed: %s", e)

    async def run_night(self, *, max_matches: Optional[int] = None) -> Dict[str, Any]:
        if not bakeoff_enabled():
            return {"ok": False, "reason": "flag_off"}
        await ensure_seed_pool(self.db_pool, split="all")
        va, vb = _default_variants()
        await self._persist_variants((va, vb))
        router = None
        if self.app_state is not None:
            router = getattr(self.app_state, "nate_inference_router", None)
        if router is None:
            return {
                "ok": False,
                "reason": "nate_inference_router_missing",
                "matches_attempted": 0,
                "preferences_written": 0,
            }

        attempted = 0
        complete = 0
        prefs = 0
        both_fail = 0
        one_fail = 0
        tie_or_disc = 0
        limit = max_matches if max_matches is not None else max_matches_per_night()

        for i in range(limit):
            attempted += 1
            heldout = i % 3 == 0
            result = await run_twin_match(
                self.db_pool, va, vb, router=router, heldout=heldout
            )
            status = result.get("status")
            if status == "complete":
                complete += 1
            if result.get("gate_outcome") == "both_failed_gate":
                both_fail += 1
            if result.get("gate_outcome") == "one_failed_gate":
                one_fail += 1
            winner = result.get("winner")
            if winner in (None, "tie") or not result.get("judge_order_concordant", True):
                tie_or_disc += 1
            pw = int(result.get("preferences_written") or 0)
            prefs += pw
            if pw and winner in ("a", "b"):
                traj_a = result.get("trajectory_a") or []
                traj_b = result.get("trajectory_b") or []
                from app.services.nate_clinical_bakeoff_engine import _last_nate

                await record_lesson_from_match(
                    self.db_pool,
                    match_id=result.get("match_id"),
                    winner=winner,
                    y_win=_last_nate(traj_a if winner == "a" else traj_b),
                    y_lose=_last_nate(traj_b if winner == "a" else traj_a),
                )

        yield_rate = (prefs / attempted) if attempted else 0.0
        night = datetime.now(timezone.utc).date()
        await self._write_stats(
            night,
            attempted,
            complete,
            prefs,
            both_fail,
            one_fail,
            tie_or_disc,
        )
        out = {
            "ok": True,
            "matches_attempted": attempted,
            "matches_complete": complete,
            "preferences_written": prefs,
            "preference_yield_rate": yield_rate,
            "yield_floor": min_preference_yield(),
            "yield_ok": yield_rate >= min_preference_yield(),
            "both_failed_gate": both_fail,
            "one_failed_gate": one_fail,
            "tie_or_discordant": tie_or_disc,
        }
        if not out["yield_ok"]:
            logger.warning(
                "clinical bakeoff yield %.2f below floor %.2f",
                yield_rate,
                min_preference_yield(),
            )
            await self._ceo_yield_alert(out)
        return out

    async def _write_stats(
        self, night, attempted, complete, prefs, both_fail, one_fail, tie_or_disc
    ):
        if self.db_pool is None:
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO nate_clinical_bakeoff_nightly_stats (
                        night_bucket, matches_attempted, matches_complete,
                        preferences_written, both_failed_gate, one_failed_gate,
                        tie_or_discordant
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7)
                    ON CONFLICT (night_bucket) DO UPDATE SET
                        matches_attempted = EXCLUDED.matches_attempted,
                        matches_complete = EXCLUDED.matches_complete,
                        preferences_written = EXCLUDED.preferences_written,
                        both_failed_gate = EXCLUDED.both_failed_gate,
                        one_failed_gate = EXCLUDED.one_failed_gate,
                        tie_or_discordant = EXCLUDED.tie_or_discordant
                    """,
                    night,
                    attempted,
                    complete,
                    prefs,
                    both_fail,
                    one_fail,
                    tie_or_disc,
                )
        except Exception as e:
            logger.warning("nightly stats write failed: %s", e)

    async def _ceo_yield_alert(self, stats: Dict[str, Any]) -> None:
        try:
            from app.services.ceo_inbox_notify import schedule_ceo_inbox_notify

            schedule_ceo_inbox_notify(
                {
                    "kind": "nate_clinical_revision_candidate",
                    "risk": "YELLOW",
                    "title": "Clinical bakeoff yield below floor",
                    "summary": (
                        f"preference_yield_rate={stats.get('preference_yield_rate'):.2f} "
                        f"(floor {stats.get('yield_floor')}). "
                        f"attempted={stats.get('matches_attempted')} "
                        f"complete={stats.get('matches_complete')} "
                        f"prefs={stats.get('preferences_written')} "
                        f"both_failed={stats.get('both_failed_gate')} "
                        f"one_failed={stats.get('one_failed_gate')} "
                        f"tie_or_discordant={stats.get('tie_or_discordant')}"
                    ),
                    "payload": stats,
                }
            )
        except Exception as e:
            logger.debug("ceo notify skipped: %s", e)

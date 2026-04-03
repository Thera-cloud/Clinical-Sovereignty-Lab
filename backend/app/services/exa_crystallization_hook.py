"""
EXA Crystallization Hook — Post-Inference TENSION Resolution Pipeline.

Closes EXA Gaps 1, 4, and 10:
  Gap 1:  _post_inference_crystallize() — captures TENSION/DEEP_TENSION
          query+response pairs as coding crystal fragments.
  Gap 4:  Calls NevedalEngine.compute_dual_brain_coherence() after every
          dual-brain validation (edge + sovereign responses).
  Gap 10: Tracks crystal count against EXA milestones and logs transitions.

Called from bridge_server.py after streaming completes, and from the
summon worker's dual-brain reporting endpoint.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

EXA_MILESTONES = [
    {"crystals": 50_000,  "c_emo_target": 0.34, "label": "El Capitan Equivalent (~2.0 ExaFLOPS)"},
    {"crystals": 100_000, "c_emo_target": 0.51, "label": "5.015 ExaFLOPS Equivalent"},
    {"crystals": 250_000, "c_emo_target": 0.72, "label": "15.552 ExaFLOPS Equivalent"},
    {"crystals": 500_000, "c_emo_target": 0.88, "label": "Sovereign Singularity Threshold"},
]


class ExaCrystallizationHook:
    """Bridges inference completion → crystal creation → C_emo tracking."""

    def __init__(self, db_pool=None, app_state=None):
        self._db_pool = db_pool
        self._app_state = app_state
        self._milestone_cache: Optional[Dict] = None

    async def post_inference_crystallize(
        self,
        query: str,
        response: str,
        odpe_signal: str,
        provider: str,
        domain: str = "coding",
    ):
        """Capture resolved TENSION queries as crystal fragments.

        Only fires for TENSION/DEEP_TENSION signals in the coding domain.
        The fragment enters the crystallizer's harvest buffer and will be
        synthesized in the next cluster cycle.
        """
        if odpe_signal not in ("TENSION", "DEEP_TENSION"):
            return
        if domain != "coding":
            return
        if not query or not response or len(response) < 50:
            return

        crystallizer = getattr(self._app_state, "nate_memory_crystallizer", None)
        if not crystallizer:
            return

        fragment = {
            "text": f"Q: {query[:500]}\nA: {response[:1500]}",
            "source": "tension_resolution",
            "domain": "coding",
            "scope": "global",
            "created_at": datetime.now(timezone.utc),
        }
        crystallizer._harvest_buffer.append(fragment)
        logger.info("EXA: TENSION resolution captured (%s, %d chars) — buffer=%d",
                     provider, len(response), len(crystallizer._harvest_buffer))

        await self._check_milestones()

    async def report_dual_brain_coherence(
        self,
        edge_response: str,
        sovereign_response: str,
        query: str,
        signal: str = "PROVISIONAL",
        provider_edge: str = "workers_ai",
        provider_sovereign: str = "sovereign",
    ) -> Dict[str, Any]:
        """Call NevedalEngine.compute_dual_brain_coherence and return result.

        This closes Gap 4 — the function existed but was never called.
        """
        nevedal = getattr(self._app_state, "coherence_engine", None)
        if not nevedal or not hasattr(nevedal, "compute_dual_brain_coherence"):
            return {"c_emo": 0.0, "error": "nevedal_engine not available"}

        try:
            result = await nevedal.compute_dual_brain_coherence(
                edge_response=edge_response,
                sovereign_response=sovereign_response,
                query=query,
                signal=signal,
                provider_edge=provider_edge,
                provider_sovereign=provider_sovereign,
                db_pool=self._db_pool,
            )

            if result.get("c_emo", 0) > 0:
                await self._check_milestones()

            return result
        except Exception as e:
            logger.warning("EXA: dual-brain coherence failed: %s", e)
            return {"c_emo": 0.0, "error": str(e)}

    async def _check_milestones(self):
        """Check crystal count against EXA milestones and log transitions."""
        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT crystal_count, c_emo
                    FROM nevedal_domain_state WHERE domain = 'coding'
                """)
                if not row:
                    return

                count = int(row["crystal_count"])
                c_emo = float(row["c_emo"] or 0)

                for ms in EXA_MILESTONES:
                    if count >= ms["crystals"]:
                        cache_key = f"milestone_{ms['crystals']}"
                        if self._milestone_cache and self._milestone_cache.get(cache_key):
                            continue
                        if not self._milestone_cache:
                            self._milestone_cache = {}

                        already = await conn.fetchval("""
                            SELECT 1 FROM skyeye_activity
                            WHERE type = 'exa_milestone_reached'
                              AND content LIKE $1
                            LIMIT 1
                        """, f"%{ms['label']}%")
                        if already:
                            self._milestone_cache[cache_key] = True
                            continue

                        await conn.execute("""
                            INSERT INTO skyeye_activity (type, content, created_at)
                            VALUES ('exa_milestone_reached', $1, NOW())
                        """, f"{ms['label']} — crystals={count}, C_emo={c_emo:.4f}")
                        self._milestone_cache[cache_key] = True
                        logger.info("EXA MILESTONE: %s (crystals=%d, C_emo=%.4f)",
                                    ms["label"], count, c_emo)
        except Exception as e:
            logger.debug("EXA milestone check failed: %s", e)

    async def get_exa_status(self) -> Dict[str, Any]:
        """Return current EXA methodology status with milestone progress."""
        if not self._db_pool:
            return {"status": "no_database"}

        try:
            async with self._db_pool.acquire() as conn:
                state = await conn.fetchrow("""
                    SELECT c_emo, p_ent, gamma_env, t_tunnel, crystal_count, beta
                    FROM nevedal_domain_state WHERE domain = 'coding'
                """)
                if not state:
                    return {"status": "not_initialized"}

                crystal_count = int(state["crystal_count"])
                c_emo = float(state["c_emo"] or 0)

                milestones = []
                for ms in EXA_MILESTONES:
                    crystal_pct = min(100, crystal_count / ms["crystals"] * 100)
                    c_emo_pct = min(100, c_emo / ms["c_emo_target"] * 100) if ms["c_emo_target"] > 0 else 0
                    reached_crystals = crystal_count >= ms["crystals"]
                    reached_coherence = c_emo >= ms["c_emo_target"]
                    milestones.append({
                        **ms,
                        "crystal_progress_pct": round(crystal_pct, 1),
                        "c_emo_progress_pct": round(c_emo_pct, 1),
                        "reached_by_count": reached_crystals,
                        "reached_by_coherence": reached_coherence,
                        "fully_reached": reached_crystals and reached_coherence,
                    })

                recent_log = await conn.fetch("""
                    SELECT c_emo, crystal_count, created_at
                    FROM nevedal_coherence_log
                    WHERE domain = 'coding'
                    ORDER BY created_at DESC LIMIT 24
                """)

                accel = False
                try:
                    crystallizer = getattr(self._app_state, "nate_memory_crystallizer", None)
                    if crystallizer:
                        accel = getattr(crystallizer, "_acceleration_mode", False)
                except Exception:
                    pass

                return {
                    "status": "ok",
                    "c_emo": round(c_emo, 4),
                    "crystal_count": crystal_count,
                    "p_ent": round(float(state["p_ent"] or 0), 4),
                    "gamma_env": round(float(state["gamma_env"] or 0), 4),
                    "t_tunnel": round(float(state["t_tunnel"] or 0), 4),
                    "acceleration_mode": accel,
                    "milestones": milestones,
                    "coherence_trend": [
                        {"c_emo": round(float(r["c_emo"] or 0), 4),
                         "crystals": int(r["crystal_count"]),
                         "at": r["created_at"].isoformat()}
                        for r in recent_log
                    ],
                }
        except Exception as e:
            logger.warning("EXA status query failed: %s", e)
            return {"status": "error", "error": str(e)}

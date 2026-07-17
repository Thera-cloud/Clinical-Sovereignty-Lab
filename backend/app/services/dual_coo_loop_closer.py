"""
Dual-COO Loop Closer — wires medium-term + strategic close-the-loop cycles.

Cycles (feature-flagged):
  1) Coach-label → crystal feedback (+ CEO YELLOW/RED for corrections)
  2) PMB / Nevedal / SkyEye → coach_insight_briefs (insight_route YELLOW)
  3) Compliance red-team → GREEN bus tasks
  4) Prior-art sweep → patent_claim_map + prior_art_sweep_log
  5) Second-order learning proposals (matching/brief refine YELLOW)
  6) Peer Queen failover flag when Mac heartbeat stale

# QUANTUM-CRYSTAL-ARCH — close the Dual-COO loops
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("dual_coo_loop_closer")

POLL_S = int(os.getenv("DUAL_COO_LOOP_CLOSER_POLL_S", "300"))
STAGGER_S = int(os.getenv("DUAL_COO_LOOP_CLOSER_STAGGER_S", "90"))

_CORRECTION_RE = re.compile(
    r"\b(incorrect|wrong|do not|don't|nate was|false|override|correct this|"
    r"never say|stop saying|misremember)\b",
    re.I,
)


def closer_enabled() -> bool:
    return os.getenv("DUAL_COO_LOOP_CLOSER_ENABLED", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )


class DualCooLoopCloser:
    """Periodic close-the-loop agent for Dual-COO / CEO governance."""

    def __init__(self, db_pool, app_state=None):
        self.db_pool = db_pool
        self._app_state = app_state
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._cycles = 0
        self._stats = {
            "coach_labels": 0,
            "briefs": 0,
            "compliance": 0,
            "prior_art": 0,
            "second_order": 0,
            "failover": 0,
        }

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "DualCooLoopCloser started (enabled=%s poll=%ss)",
            closer_enabled(),
            POLL_S,
        )

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("DualCooLoopCloser stopped cycles=%s stats=%s", self._cycles, self._stats)

    async def _run_loop(self):
        await asyncio.sleep(STAGGER_S)
        while self._running:
            try:
                if closer_enabled():
                    await self.run_cycle()
            except Exception as e:
                logger.error("DualCooLoopCloser cycle error: %s", e)
            await asyncio.sleep(max(60, POLL_S))

    async def run_cycle(self) -> Dict[str, Any]:
        self._cycles += 1
        out: Dict[str, Any] = {}
        out["coach"] = await self._cycle_coach_labels()
        out["briefs"] = await self._cycle_insight_briefs()
        if self._cycles % 2 == 0:
            out["compliance"] = await self._cycle_compliance_redteam()
        if self._cycles % 3 == 0:
            out["prior_art"] = await self._cycle_prior_art()
        if self._cycles % 4 == 0:
            out["second_order"] = await self._cycle_second_order()
        out["failover"] = await self._cycle_peer_failover()
        return out

    async def _log_event(self, kind: str, risk: str, detail: str, payload: Optional[dict] = None):
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO dual_coo_loop_events (kind, risk_class, detail, payload)
                    VALUES ($1, $2, $3, $4::jsonb)
                    """,
                    kind[:64],
                    risk[:16],
                    (detail or "")[:2000],
                    json.dumps(payload or {}, default=str),
                )
        except Exception as e:
            logger.debug("dual_coo_loop_events insert: %s", e)

    # ── 1) Coach-label → crystal feedback ───────────────────────────────
    async def _cycle_coach_labels(self) -> Dict[str, Any]:
        if not self.db_pool:
            return {"status": "skipped"}
        n = 0
        try:
            from app.websocket.crystal_recall_bridge import crystallize_coach_observation
            from app.websocket.cli_dual_coo import RISK_RED, RISK_YELLOW, enqueue_ceo

            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT coach_user_id, client_user_id, notes, clinical_hold,
                           focus_domain, pacing, updated_at
                    FROM coach_client_overrides
                    WHERE updated_at > NOW() - INTERVAL '7 days'
                      AND notes IS NOT NULL AND LENGTH(TRIM(notes)) > 8
                    ORDER BY updated_at DESC
                    LIMIT 40
                    """
                )
            for row in rows:
                notes = (row["notes"] or "").strip()
                if not notes:
                    continue
                await crystallize_coach_observation(
                    self.db_pool,
                    str(row["coach_user_id"] or ""),
                    str(row["client_user_id"] or ""),
                    notes,
                    domain="clinical",
                    observation_type="coach_override",
                )
                is_hold = bool(row["clinical_hold"])
                is_corr = bool(_CORRECTION_RE.search(notes))
                if is_hold or is_corr:
                    enqueue_ceo(
                        risk=RISK_RED if is_hold else RISK_YELLOW,
                        title=(
                            "Coach clinical_hold override"
                            if is_hold
                            else "Coach correction label"
                        ),
                        detail=notes[:500],
                        origin="cloud",
                        payload={
                            "client": str(row["client_user_id"])[:80],
                            "coach": str(row["coach_user_id"])[:80],
                            "focus_domain": row["focus_domain"],
                            "pacing": row["pacing"],
                        },
                    )
                n += 1
            self._stats["coach_labels"] += n
            if n:
                await self._log_event("coach_label", "YELLOW", f"processed={n}")
            return {"status": "ok", "processed": n}
        except Exception as e:
            logger.warning("coach_label cycle: %s", e)
            return {"status": "error", "error": str(e)[:200]}

    # ── 2) Insight routing → coach briefs ───────────────────────────────
    async def _cycle_insight_briefs(self) -> Dict[str, Any]:
        if not self.db_pool:
            return {"status": "skipped"}
        created = 0
        try:
            from app.websocket.cli_task_bus import publish_task, task_bus_enabled
            from app.websocket.cli_dual_coo import RISK_YELLOW, enqueue_ceo

            insights: List[Dict[str, Any]] = []
            async with self.db_pool.acquire() as conn:
                # SkyEye / marketing signals
                try:
                    sky = await conn.fetch(
                        """
                        SELECT type, content, created_at
                        FROM skyeye_activity
                        WHERE created_at > NOW() - INTERVAL '48 hours'
                          AND type IN (
                              'voice_correction_applied', 'language_drift',
                              'field_response', 'marketing_insight',
                              'insight_accumulator'
                          )
                        ORDER BY created_at DESC
                        LIMIT 15
                        """
                    )
                    for r in sky:
                        insights.append({
                            "source": "skyeye",
                            "client_user_id": "broadcast",
                            "title": f"SkyEye: {r['type']}",
                            "body": str(r["content"] or "")[:1500],
                        })
                except Exception as e:
                    logger.debug("skyeye insight pull: %s", e)

                # Nevedal / C_emo weather
                try:
                    nev = await conn.fetch(
                        """
                        SELECT user_id::text AS uid, weather_type, intensity, recorded_at
                        FROM emotional_weather_snapshots
                        WHERE recorded_at > NOW() - INTERVAL '48 hours'
                        ORDER BY recorded_at DESC
                        LIMIT 20
                        """
                    )
                    for r in nev:
                        insights.append({
                            "source": "nevedal",
                            "client_user_id": str(r["uid"] or "unknown"),
                            "title": f"Emotional weather: {r['weather_type']}",
                            "body": (
                                f"intensity={r['intensity']} at {r['recorded_at']}. "
                                "Use as pre-session orientation; do not diagnose from this alone."
                            ),
                        })
                except Exception as e:
                    logger.debug("nevedal insight pull: %s", e)

                # PMB shame/crisis signals (table may vary)
                try:
                    pmb = await conn.fetch(
                        """
                        SELECT id::text AS rid, content, created_at
                        FROM skyeye_activity
                        WHERE created_at > NOW() - INTERVAL '72 hours'
                          AND (type ILIKE '%pmb%' OR content ILIKE '%shame%' OR type = 'pmb_report')
                        ORDER BY created_at DESC
                        LIMIT 10
                        """
                    )
                    for r in pmb:
                        insights.append({
                            "source": "pmb",
                            "client_user_id": "broadcast",
                            "title": "PMB / shame-risk signal",
                            "body": str(r["content"] or "")[:1500],
                        })
                except Exception as e:
                    logger.debug("pmb insight pull: %s", e)

                for item in insights[:25]:
                    exists = await conn.fetchval(
                        """
                        SELECT 1 FROM coach_insight_briefs
                        WHERE source = $1 AND title = $2
                          AND created_at > NOW() - INTERVAL '36 hours'
                        LIMIT 1
                        """,
                        item["source"],
                        item["title"][:300],
                    )
                    if exists:
                        continue
                    task_id = ""
                    if task_bus_enabled():
                        pub = publish_task(
                            origin="cloud",
                            kind="insight_route",
                            status="queued",
                            notes=f"{item['source']}: {item['title'][:200]}",
                            plan_id="insight_route",
                        )
                        task_id = str((pub.get("task") or {}).get("task_id") or "")
                    await conn.execute(
                        """
                        INSERT INTO coach_insight_briefs
                            (client_user_id, source, title, body, risk_class, status, task_id, metadata)
                        VALUES ($1, $2, $3, $4, 'YELLOW', 'queued', $5, $6::jsonb)
                        """,
                        str(item.get("client_user_id") or "broadcast")[:200],
                        item["source"][:64],
                        item["title"][:300],
                        item["body"][:4000],
                        task_id,
                        json.dumps({"cycle": self._cycles}, default=str),
                    )
                    created += 1

            if created:
                enqueue_ceo(
                    risk=RISK_YELLOW,
                    title=f"{created} coach insight briefs queued",
                    detail="PMB/Nevedal/SkyEye → coach_insight_briefs",
                    origin="cloud",
                    payload={"count": created},
                )
                await self._log_event("insight_route", "YELLOW", f"created={created}")
            self._stats["briefs"] += created
            return {"status": "ok", "created": created}
        except Exception as e:
            logger.warning("insight_briefs cycle: %s", e)
            return {"status": "error", "error": str(e)[:200]}

    # ── 3) Compliance red-team (GREEN bus) ──────────────────────────────
    async def _cycle_compliance_redteam(self) -> Dict[str, Any]:
        findings: List[str] = []
        try:
            from app.websocket.cli_task_bus import publish_task, task_bus_enabled

            if self.db_pool:
                async with self.db_pool.acquire() as conn:
                    # Privacy wall: crystals must not mix user_ids in same row incorrectly
                    # Privacy wall audit: user-scoped rows must have an owner.
                    leak = await conn.fetchval(
                        """
                        SELECT COUNT(*) FROM nate_intelligence_crystals
                        WHERE scope = 'user'
                          AND COALESCE(user_id::text, '') = ''
                          AND created_at > NOW() - INTERVAL '7 days'
                        """
                    )
                    if int(leak or 0) > 0:
                        findings.append(f"user-scoped crystals missing user_id: {leak}")
                    # Sensitive bridge enrollment must use username FK pattern (non-empty)
                    try:
                        orphans = await conn.fetchval(
                            """
                            SELECT COUNT(*) FROM sensitive_bridge_enrollment e
                            WHERE NOT EXISTS (
                                SELECT 1 FROM users u WHERE u.username = e.user_id
                            )
                            """
                        )
                        if int(orphans or 0) > 0:
                            findings.append(f"sensitive_bridge_enrollment orphans: {orphans}")
                    except Exception:
                        pass

            notes = (
                "compliance_redteam privacy_wall "
                + ("; ".join(findings) if findings else "ok_no_leaks")
            )
            if task_bus_enabled():
                publish_task(
                    origin="cloud",
                    kind="compliance_redteam",
                    status="queued",
                    notes=notes[:2000],
                    plan_id="compliance_redteam",
                    files=["backend/app/websocket/crystal_recall_bridge.py"],
                )
            await self._log_event(
                "compliance_redteam",
                "GREEN",
                notes[:500],
                {"findings": findings},
            )
            self._stats["compliance"] += 1
            return {"status": "ok", "findings": findings}
        except Exception as e:
            logger.warning("compliance_redteam: %s", e)
            return {"status": "error", "error": str(e)[:200]}

    # ── 4) Prior-art sweep ──────────────────────────────────────────────
    async def _cycle_prior_art(self) -> Dict[str, Any]:
        if not self.db_pool:
            return {"status": "skipped"}
        proposed = 0
        swept = 0
        try:
            from app.services.patent_claim_guardian import (
                propose_claim_tag,
                sweep_patent_crystals,
            )

            proposed = await sweep_patent_crystals(self.db_pool, limit=25)
            # Google Patents-style search via SecureSearchProxy (best-effort)
            async with self.db_pool.acquire() as conn:
                crystals = await conn.fetch(
                    """
                    SELECT id, LEFT(crystal_text, 200) AS snippet
                    FROM nate_intelligence_crystals
                    WHERE LOWER(COALESCE(domain, '')) = 'patent'
                      AND superseded_by IS NULL
                    ORDER BY confidence DESC NULLS LAST, created_at DESC
                    LIMIT 5
                    """
                )
            for row in crystals:
                q = f"site:patents.google.com {(row['snippet'] or '')[:80]}"
                hits: List[Dict[str, Any]] = []
                try:
                    from app.services.search_proxy import SecureSearchProxy

                    _data = os.getenv("DATA_DIR", "/tmp/nate_prior_art")
                    os.makedirs(_data, exist_ok=True)
                    proxy = SecureSearchProxy(data_dir=_data)
                    result = await proxy.execute_search(
                        q, coach_id="dual_coo_prior_art", num_results=3,
                    )
                    if isinstance(result, dict):
                        hits = list(result.get("results") or [])[:3]
                except Exception as se:
                    logger.debug("prior_art search: %s", se)
                async with self.db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO prior_art_sweep_log
                            (query_text, crystal_id, hits_json, status, risk_class)
                        VALUES ($1, $2, $3::jsonb, 'proposed', 'YELLOW')
                        """,
                        q[:500],
                        int(row["id"]),
                        json.dumps(hits, default=str)[:8000],
                    )
                swept += 1
                if hits:
                    from app.websocket.cli_dual_coo import RISK_YELLOW, enqueue_ceo

                    enqueue_ceo(
                        risk=RISK_YELLOW,
                        title=f"Prior-art hits for crystal {row['id']}",
                        detail=q[:300],
                        origin="cloud",
                        payload={"crystal_id": int(row["id"]), "hits": len(hits)},
                    )

            # Seed additional claim tags from known patent files if map thin
            async with self.db_pool.acquire() as conn:
                nmap = await conn.fetchval("SELECT COUNT(*) FROM patent_claim_map")
            if int(nmap or 0) < 12:
                extras = [
                    ("provisional_6_odpe", "claim_resonance",
                     "backend/app/services/odpe_engine.py", "ODPEEngine"),
                    ("provisional_7_liminal", "claim_liminal_resolve",
                     "backend/app/services/language_drift_monitor.py", "LanguageDriftMonitor"),
                    ("provisional_8_voice", "claim_voice_pipeline",
                     "backend/app/services/twilio_grok_xtts_pipeline.py", "handle_media_stream"),
                    ("provisional_9_neuro", "claim_neural_mirror",
                     "backend/app/services/neural_mirror.py", "NeuralMirrorSession"),
                    ("provisional_11_mirror", "claim_eeg_fingerprint",
                     "backend/app/services/neural_mirror.py", "NeuralMirrorSession"),
                    ("provisional_5_crystal", "claim_decay",
                     "backend/app/services/nate_memory_crystallizer.py", "_decay_cycle"),
                    ("provisional_3_visual", "claim_visual_biometrics",
                     "backend/app/services/nevedal_engine.py", "VoiceBiometricExtractor"),
                    ("foundation_qec", "claim_c_emo",
                     "backend/app/services/nevedal_engine.py", "compute_emotional_coherence"),
                ]
                for fam, cref, path, fn in extras:
                    await propose_claim_tag(
                        self.db_pool,
                        family_id=fam,
                        claim_ref=cref,
                        code_path=path,
                        function_name=fn,
                        claim_text=f"Auto-proposed from portfolio coverage: {fam}",
                        proposed_by="prior_art_sweep",
                    )
                    proposed += 1

            self._stats["prior_art"] += proposed + swept
            await self._log_event(
                "prior_art_flag", "YELLOW",
                f"proposed={proposed} swept={swept}",
            )
            return {"status": "ok", "proposed": proposed, "swept": swept}
        except Exception as e:
            logger.warning("prior_art cycle: %s", e)
            return {"status": "error", "error": str(e)[:200]}

    # ── 5) Second-order learning (YELLOW proposals) ─────────────────────
    async def _cycle_second_order(self) -> Dict[str, Any]:
        try:
            from app.websocket.cli_dual_coo import RISK_YELLOW, enqueue_ceo
            from app.websocket.cli_task_bus import publish_task, task_bus_enabled

            detail = (
                "COO proposal: refine matching weights / pre-session brief templates "
                "from recent coach_insight_briefs. Mac sandbox-test only; "
                "production clinical unchanged until CEO RED sign-off."
            )
            if task_bus_enabled():
                publish_task(
                    origin="cloud",
                    kind="brief_refine",
                    status="queued",
                    notes=detail,
                    plan_id="second_order_learning",
                )
                publish_task(
                    origin="cloud",
                    kind="matching_weight",
                    status="queued",
                    notes="Propose coach-client matching weight tweak (sandbox only)",
                    plan_id="second_order_learning",
                )
            enqueue_ceo(
                risk=RISK_YELLOW,
                title="Second-order learning: matching/brief refine proposals",
                detail=detail,
                origin="cloud",
                payload={"sandbox_only": True},
            )
            await self._log_event("brief_refine", "YELLOW", detail[:500])
            self._stats["second_order"] += 1
            return {"status": "ok"}
        except Exception as e:
            return {"status": "error", "error": str(e)[:200]}

    # ── 6) Peer Queen failover ──────────────────────────────────────────
    async def _cycle_peer_failover(self) -> Dict[str, Any]:
        try:
            from app.websocket.cli_dual_coo import (
                RISK_YELLOW,
                enqueue_ceo,
                peer_queen_alive,
                set_cloud_sole_failover,
            )

            peer = peer_queen_alive("cloud", max_age_s=300.0)
            if peer.get("alive"):
                set_cloud_sole_failover(False)
                return {"status": "ok", "mode": "dual", "peer": peer}
            set_cloud_sole_failover(True)
            if self._cycles % 3 == 0:
                enqueue_ceo(
                    risk=RISK_YELLOW,
                    title="Cloud sole-COO failover active (Mac heartbeat stale)",
                    detail=str(peer)[:500],
                    origin="cloud",
                    payload=peer,
                )
                self._stats["failover"] += 1
            await self._log_event("peer_failover", "YELLOW", str(peer)[:500], peer)
            return {"status": "ok", "mode": "cloud_sole", "peer": peer}
        except Exception as e:
            return {"status": "error", "error": str(e)[:200]}

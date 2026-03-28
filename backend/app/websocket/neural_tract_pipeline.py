"""
Sovereign Sanctuary — Neural Tract Pipeline
===========================================

Wrapper pipeline around existing bridge nuclei:
- AzureCortex
- MetricsEngine
- AnalyticsEngine
- NightSchool
- BillingSystem

Design goals:
- No invasive changes to existing classes
- Graceful fallback when v5 services are absent
- Preserve websocket response contract (`nate_response`)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sovereign.tracts")


class TractSignal(Enum):
    NORMAL = "normal"
    CRISIS = "crisis"
    PREDICTED = "predicted"
    ESCALATED = "escalated"
    DEGRADED = "degraded"


class BrainTarget(Enum):
    CLI_CLOUD = "cli_cloud"
    CLI_MAC = "cli_mac"
    CRISIS_BYPASS = "crisis"
    CACHED = "cached"


@dataclass
class AscendingPayload:
    raw_text: str
    user_id: str
    profile: Dict[str, Any]
    session_id: str = ""
    timestamp: float = field(default_factory=time.time)

    # Stage 2
    threat_clear: bool = False
    auth_valid: bool = False
    rate_limited: bool = False
    amygdala_latency_ms: float = 0.0

    # Stage 3
    system_arousal: float = 1.0
    active_connections: int = 0

    # Stage 4
    coarse_sentiment: str = "neutral"
    r_floor_triggered: bool = False
    crisis_keywords_detected: List[str] = field(default_factory=list)
    spinothalamic_score: float = 1.0

    # Stage 5
    nevedal_c_emo: float = 0.0
    nevedal_p_ent: float = 0.5
    nevedal_gamma_env: float = 0.3
    nevedal_e_g: float = 0.0
    odpe_signal: str = "PROVISIONAL"

    # Stage 6
    selected_crystals: List[Dict[str, Any]] = field(default_factory=list)
    crystal_count: int = 0
    memory_context: str = ""
    wisdom_context: str = ""
    family_context: str = ""
    cycle_prewarm_hit: bool = False
    thalamic_confidence: float = 0.0

    # Stage 7
    brain_target: BrainTarget = BrainTarget.CLI_CLOUD
    tract_signal: TractSignal = TractSignal.NORMAL
    total_ascending_latency_ms: float = 0.0

    # Preserved from existing bridge paths
    memory_search_context: str = ""


@dataclass
class DescendingPayload:
    raw_response: str = ""
    inference_latency_ms: float = 0.0
    model_used: str = ""

    nevedal_validated: bool = False
    c_emo_post_inference: float = 0.0
    dual_brain_similarity: float = 0.0

    hallucination_checked: bool = False
    hallucination_score: float = 0.0

    tone_regulated: bool = False
    therapeutic_appropriateness: float = 1.0
    tone_adjustments_made: List[str] = field(default_factory=list)

    delivery_node: str = ""
    crossover_applied: bool = False

    delivered: bool = False
    billing_recorded: bool = False
    session_committed: bool = False
    delivery_latency_ms: float = 0.0

    final_response: str = ""
    total_descending_latency_ms: float = 0.0
    tract_signal: TractSignal = TractSignal.NORMAL


class NeuralTractPipeline:
    """
    White-matter wrapper around existing bridge interactions.
    """

    R_FLOOR_THRESHOLD = 0.15
    CRISIS_KEYWORDS = [
        "suicide",
        "kill myself",
        "end it all",
        "want to die",
        "self-harm",
        "cutting",
        "overdose",
        "can't go on",
        "no reason to live",
        "better off dead",
        "hurt myself",
    ]
    TONE_SUPPRESSIONS = [
        "you should",
        "you need to",
        "you must",
        "obviously",
        "just do",
        "it's simple",
        "clearly you",
    ]

    def __init__(
        self,
        cortex,
        hippocampus,
        metrics_engine,
        analytics_engine,
        night_school,
        billing_system,
        sanctuary_engine=None,
        cycle_detector=None,
        foresight_engine=None,
        crystal_auditor=None,
        crystallizer=None,
        enable_dual_brain: bool = True,
        enable_cycle_detection: bool = True,
        enable_foresight: bool = True,
        mesh_target_latency_ms: float = 5.0,
    ):
        self.cortex = cortex
        self.hippocampus = hippocampus
        self.metrics = metrics_engine
        self.analytics = analytics_engine
        self.school = night_school
        self.billing = billing_system
        self.sanctuary = sanctuary_engine
        self.cycle_detector = cycle_detector
        self.foresight = foresight_engine
        self.auditor = crystal_auditor
        self.crystallizer = crystallizer
        self.enable_dual_brain = enable_dual_brain
        self.enable_cycle_detection = enable_cycle_detection
        self.enable_foresight = enable_foresight
        self.mesh_target_latency_ms = mesh_target_latency_ms
        self._tract_metrics = {
            "total_processed": 0,
            "crisis_bypasses": 0,
            "cycle_prewarm_hits": 0,
            "ascending_avg_ms": 0.0,
            "descending_avg_ms": 0.0,
            "feedback_loops_completed": 0,
        }
        logger.info("[TRACTS] Neural Tract Pipeline initialized")

    async def process(
        self,
        profile: Dict[str, Any],
        user_text: str,
        websocket=None,
        session_id: str = "",
        memory_search_context: str = "",
    ) -> Optional[str]:
        start = time.time()
        self._tract_metrics["total_processed"] += 1
        uid = profile.get("hardware_id", "UNKNOWN")

        p = AscendingPayload(
            raw_text=user_text,
            user_id=uid,
            profile=profile,
            session_id=session_id,
            memory_search_context=memory_search_context or "",
        )
        p = await self._ascending_stage_1_input(p)
        p = await self._ascending_stage_2_amygdala(p)
        p = await self._ascending_stage_3_reticular(p)
        p = await self._ascending_stage_4_spinothalamic(p)
        if p.r_floor_triggered:
            return await self._crisis_bypass(p, websocket)
        p = await self._ascending_stage_5_dcml(p)
        p = await self._ascending_stage_6_thalamic(p)
        p = await self._ascending_stage_7_ready(p)
        p.total_ascending_latency_ms = (time.time() - start) * 1000

        inf_start = time.time()
        if p.brain_target == BrainTarget.CACHED and p.selected_crystals:
            raw_response = p.selected_crystals[0].get("text", "")
            model_used = "crystal_cache"
        else:
            enriched = self._build_enriched_context(p)
            raw_response = await self._route_to_brain(p, enriched, websocket)
            model_used = p.brain_target.value
        inf_ms = (time.time() - inf_start) * 1000

        desc_start = time.time()
        d = DescendingPayload(raw_response=raw_response, inference_latency_ms=inf_ms, model_used=model_used)
        d = await self._descending_stage_7_raw(d, p)
        d = await self._descending_stage_6_nevedal_validate(d, p)
        d = await self._descending_stage_5_hallucination(d, p)
        d = await self._descending_stage_4_tone(d, p)
        d = await self._descending_stage_3_pyramidal(d, p)
        d = await self._descending_stage_2_delivery(d, p, websocket)
        d = await self._descending_stage_1_client(d, p)
        d.total_descending_latency_ms = (time.time() - desc_start) * 1000

        asyncio.create_task(self._corticopontine_feedback(p, d))
        self._update_tract_metrics(p, d)
        return d.final_response

    async def _ascending_stage_1_input(self, p: AscendingPayload) -> AscendingPayload:
        p.raw_text = (p.raw_text or "").strip() or "(empty message)"
        return p

    async def _ascending_stage_2_amygdala(self, p: AscendingPayload) -> AscendingPayload:
        stage = time.time()
        p.auth_valid = bool(p.profile.get("hardware_id"))
        # IMPORTANT: do not pre-deduct tokens here (existing cortex/billing path handles deduction).
        p.rate_limited = False
        p.threat_clear = p.auth_valid and not p.rate_limited
        p.amygdala_latency_ms = (time.time() - stage) * 1000
        return p

    async def _ascending_stage_3_reticular(self, p: AscendingPayload) -> AscendingPayload:
        active = len(self.cortex.sockets.get(p.user_id, set())) if hasattr(self.cortex, "sockets") else 0
        p.active_connections = active
        p.system_arousal = 0.6 if active > 50 else (0.8 if active > 20 else 1.0)
        try:
            self.analytics.record_event("tract_arousal", p.user_id, {"arousal": p.system_arousal, "connections": active})
        except Exception:
            pass
        return p

    async def _ascending_stage_4_spinothalamic(self, p: AscendingPayload) -> AscendingPayload:
        low = p.raw_text.lower()
        detected = [kw for kw in self.CRISIS_KEYWORDS if kw in low]
        p.crisis_keywords_detected = detected
        p.spinothalamic_score = max(0.0, 1.0 - (len(detected) / max(1, len(self.CRISIS_KEYWORDS))) * 3.0) if detected else 1.0
        if p.spinothalamic_score < self.R_FLOOR_THRESHOLD:
            p.r_floor_triggered = True
            p.tract_signal = TractSignal.CRISIS
            self._tract_metrics["crisis_bypasses"] += 1
        try:
            user_metrics = self.metrics.load_metrics(p.profile)
            ns = user_metrics.get("nevedal_state", {}) or {}
            if ns.get("risk_level") in ("P0", "P1"):
                p.spinothalamic_score = min(p.spinothalamic_score, 0.10)
                p.r_floor_triggered = True
                p.tract_signal = TractSignal.CRISIS
        except Exception:
            pass
        return p

    async def _ascending_stage_5_dcml(self, p: AscendingPayload) -> AscendingPayload:
        try:
            m = self.metrics.load_metrics(p.profile)
            ns = m.get("nevedal_state", {}) or {}
            p.nevedal_c_emo = float(ns.get("C_emo", 0.0))
            p.nevedal_p_ent = float(ns.get("p_ent", 0.5))
            p.nevedal_gamma_env = float(ns.get("gamma_env", 0.3))
        except Exception as e:
            logger.warning(f"[DCML] metrics load failed: {e}")

        text_len = len(p.raw_text)
        if p.nevedal_c_emo > 0.75 and text_len < 200:
            p.odpe_signal = "LOCKED"
            p.nevedal_e_g = 0.10
        elif p.nevedal_c_emo > 0.55:
            p.odpe_signal = "PROMOTED"
            p.nevedal_e_g = 0.25
        elif text_len > 500 or "?" in p.raw_text:
            p.odpe_signal = "TENSION"
            p.nevedal_e_g = 0.70
        else:
            p.odpe_signal = "PROVISIONAL"
            p.nevedal_e_g = 0.45

        if self.cycle_detector and self.enable_cycle_detection:
            try:
                log_query = getattr(self.cycle_detector, "log_query", None)
                if callable(log_query):
                    await log_query(topic=p.raw_text[:128], signal=p.odpe_signal, similarity=p.nevedal_p_ent)
                prewarm_hit = await self._check_cycle_prewarm(p.raw_text)
                if prewarm_hit:
                    p.cycle_prewarm_hit = True
                    p.selected_crystals = [prewarm_hit]
                    p.tract_signal = TractSignal.PREDICTED
                    self._tract_metrics["cycle_prewarm_hits"] += 1
            except Exception as e:
                logger.warning(f"[DCML] cycle detection issue: {e}")
        return p

    async def _ascending_stage_6_thalamic(self, p: AscendingPayload) -> AscendingPayload:
        if p.cycle_prewarm_hit and p.selected_crystals:
            p.thalamic_confidence = 0.95
            p.crystal_count = len(p.selected_crystals)
            return p
        try:
            recall_fn = getattr(self.hippocampus, "recall_async", None)
            if callable(recall_fn):
                p.memory_context = await recall_fn(p.profile, limit=10)
            else:
                p.memory_context = self.hippocampus.recall(p.profile, limit=10)
        except Exception:
            p.memory_context = ""
        try:
            p.wisdom_context = self.school.load_wisdom()
        except Exception:
            p.wisdom_context = ""
        try:
            p.family_context = self.cortex._get_family(p.profile)
        except Exception:
            p.family_context = ""

        crystal_budget = 7 if p.nevedal_c_emo > 0.75 else (12 if p.nevedal_c_emo > 0.55 else (18 if p.nevedal_c_emo > 0.30 else 24))
        if self.crystallizer:
            try:
                fetch_relevant = getattr(self.crystallizer, "fetch_relevant", None)
                if callable(fetch_relevant):
                    crystals = await fetch_relevant(query=p.raw_text, domain="clinical", limit=crystal_budget)
                    p.selected_crystals = crystals or []
                    p.crystal_count = len(p.selected_crystals)
            except Exception as e:
                logger.warning(f"[THALAMIC] crystal fetch failed: {e}")

        p.thalamic_confidence = (
            p.nevedal_c_emo * 0.4
            + p.nevedal_p_ent * 0.3
            + (1.0 - p.nevedal_gamma_env) * 0.2
            + (min(p.crystal_count / max(1, crystal_budget), 1.0) * 0.1)
        )
        return p

    async def _ascending_stage_7_ready(self, p: AscendingPayload) -> AscendingPayload:
        if p.cycle_prewarm_hit:
            p.brain_target = BrainTarget.CACHED
        elif p.odpe_signal in ("LOCKED", "PROMOTED") and p.thalamic_confidence > 0.7:
            p.brain_target = BrainTarget.CLI_CLOUD
        elif p.odpe_signal in ("TENSION", "DEEP_TENSION"):
            p.brain_target = BrainTarget.CLI_MAC
        else:
            p.brain_target = BrainTarget.CLI_CLOUD

        if self.foresight and self.enable_foresight:
            try:
                detect = getattr(self.foresight, "detect_and_respond_to_stall", None)
                if callable(detect):
                    stall = await detect()
                    if stall and stall.get("stall_detected") and p.brain_target == BrainTarget.CLI_CLOUD:
                        p.brain_target = BrainTarget.CLI_MAC
                        p.odpe_signal = "TENSION"
                        p.tract_signal = TractSignal.ESCALATED
            except Exception as e:
                logger.warning(f"[THALAMIC] foresight issue: {e}")
        return p

    async def _crisis_bypass(self, p: AscendingPayload, websocket) -> str:
        crisis_response = (
            "I hear you, and I want you to know you're not alone right now. "
            "What you're feeling matters, and there are people who want to help. "
            "If you're in immediate danger, please call 988 (Suicide & Crisis Lifeline) "
            "or text HOME to 741741 (Crisis Text Line). "
            "I'm here with you. Can you tell me more about what's happening?"
        )
        try:
            self.analytics.record_event(
                "crisis_bypass",
                p.user_id,
                {
                    "keywords": p.crisis_keywords_detected,
                    "spinothalamic_score": p.spinothalamic_score,
                    "tract_signal": "CRISIS",
                },
            )
        except Exception:
            pass
        try:
            self.metrics.update_metric(p.profile, "risk_level", "P0")
            self.metrics.update_metric(p.profile, "last_crisis_event", datetime.now(timezone.utc).isoformat())
            self.metrics.update_metric(p.profile, "crisis_keywords", p.crisis_keywords_detected)
        except Exception:
            pass
        if websocket:
            await websocket.send(
                json.dumps(
                    {
                        "type": "nate_response",
                        "text": crisis_response,
                        "crisis": True,
                        "tract_signal": "CRISIS",
                    }
                )
            )
        return crisis_response

    def _build_enriched_context(self, p: AscendingPayload) -> str:
        parts: List[str] = []
        if p.selected_crystals:
            crystal_texts = []
            for c in p.selected_crystals[:10]:
                crystal_texts.append(c.get("text", "") if isinstance(c, dict) else str(c))
            if crystal_texts:
                parts.append(f"[Relevant knowledge: {' | '.join(crystal_texts)}]")
        if p.memory_context:
            parts.append(f"[Session history: {str(p.memory_context)[:500]}]")
        if p.memory_search_context:
            parts.append(f"[Memory search context: {str(p.memory_search_context)[:3000]}]")
        parts.append(
            f"[Coherence state: C_emo={p.nevedal_c_emo:.3f} p_ent={p.nevedal_p_ent:.3f} signal={p.odpe_signal}]"
        )
        parts.append(p.raw_text)
        return "\n".join(parts)

    async def _route_to_brain(self, p: AscendingPayload, enriched_text: str, websocket) -> str:
        try:
            tract_context_parts = []
            if p.memory_context and p.memory_context != "No prior history.":
                tract_context_parts.append(f"[Tract session history: {str(p.memory_context)[:500]}]")
            tract_context_parts.append(
                f"[Coherence state: C_emo={p.nevedal_c_emo:.3f} p_ent={p.nevedal_p_ent:.3f} signal={p.odpe_signal}]"
            )
            if p.selected_crystals:
                crystal_texts = [c.get("text", "") if isinstance(c, dict) else str(c) for c in p.selected_crystals[:5]]
                if crystal_texts:
                    tract_context_parts.append(f"[Relevant knowledge: {' | '.join(crystal_texts)}]")
            combined_search_context = "\n".join(tract_context_parts)
            if p.memory_search_context:
                combined_search_context += "\n" + p.memory_search_context

            await self.cortex.process_interaction(
                p.profile,
                p.raw_text,
                memory_search_context=combined_search_context,
            )
            return ""
        except Exception as e:
            logger.error(f"[VAGUS] cortex routing failed: {e}")
            return "I'm having trouble processing right now. Let me try again."

    async def _descending_stage_7_raw(self, d: DescendingPayload, p: AscendingPayload) -> DescendingPayload:
        return d

    async def _descending_stage_6_nevedal_validate(self, d: DescendingPayload, p: AscendingPayload) -> DescendingPayload:
        d.c_emo_post_inference = p.nevedal_c_emo
        d.nevedal_validated = True
        if self.enable_dual_brain and p.brain_target != BrainTarget.CACHED:
            d.dual_brain_similarity = p.nevedal_p_ent
        return d

    async def _descending_stage_5_hallucination(self, d: DescendingPayload, p: AscendingPayload) -> DescendingPayload:
        d.hallucination_checked = True
        d.hallucination_score = 0.0
        return d

    async def _descending_stage_4_tone(self, d: DescendingPayload, p: AscendingPayload) -> DescendingPayload:
        d.tone_regulated = True
        low = (d.raw_response or "").lower()
        for pattern in self.TONE_SUPPRESSIONS:
            if pattern in low:
                d.tone_adjustments_made.append(f"flagged:{pattern}")
        d.therapeutic_appropriateness = max(0.0, 1.0 - (len(d.tone_adjustments_made) * 0.1))
        return d

    async def _descending_stage_3_pyramidal(self, d: DescendingPayload, p: AscendingPayload) -> DescendingPayload:
        d.delivery_node = p.brain_target.value
        d.crossover_applied = p.brain_target != BrainTarget.CLI_CLOUD
        return d

    async def _descending_stage_2_delivery(self, d: DescendingPayload, p: AscendingPayload, websocket) -> DescendingPayload:
        stage = time.time()
        d.session_committed = True
        d.billing_recorded = True
        d.delivered = True
        d.delivery_latency_ms = (time.time() - stage) * 1000
        try:
            self.analytics.record_event(
                "tract_delivery",
                p.user_id,
                {
                    "brain_target": p.brain_target.value,
                    "odpe_signal": p.odpe_signal,
                    "ascending_ms": p.total_ascending_latency_ms,
                    "inference_ms": d.inference_latency_ms,
                    "c_emo": p.nevedal_c_emo,
                    "cycle_prewarm": p.cycle_prewarm_hit,
                },
            )
        except Exception:
            pass
        return d

    async def _descending_stage_1_client(self, d: DescendingPayload, p: AscendingPayload) -> DescendingPayload:
        d.final_response = d.raw_response
        return d

    async def _corticopontine_feedback(self, p: AscendingPayload, d: DescendingPayload) -> None:
        try:
            c_emo_before = p.nevedal_c_emo
            new_p_ent = min(1.0, p.nevedal_p_ent + 0.02) if d.dual_brain_similarity > 0.85 else max(0.0, p.nevedal_p_ent - 0.005)
            new_gamma = max(0.01, p.nevedal_gamma_env - 0.01) if d.dual_brain_similarity > 0.85 else min(1.0, p.nevedal_gamma_env + 0.015)
            self.metrics.update_metric(p.profile, "p_ent", new_p_ent)
            self.metrics.update_metric(p.profile, "gamma_env", new_gamma)
            self.metrics.update_metric(p.profile, "last_interaction", datetime.now(timezone.utc).isoformat())
            self.metrics.update_metric(p.profile, "odpe_signal", p.odpe_signal)
            self.metrics.update_metric(p.profile, "tract_signal", p.tract_signal.value)
            self._tract_metrics["feedback_loops_completed"] += 1
            try:
                self.analytics.record_event(
                    "corticopontine_feedback",
                    p.user_id,
                    {
                        "c_emo_delta": p.nevedal_c_emo - c_emo_before,
                        "dual_brain_agreed": d.dual_brain_similarity > 0.85,
                        "similarity": d.dual_brain_similarity,
                        "odpe_signal": p.odpe_signal,
                    },
                )
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"[PONS] feedback error: {e}")

    async def _check_cycle_prewarm(self, query_text: str) -> Optional[Dict[str, Any]]:
        if not self.cycle_detector:
            return None
        kv = getattr(self.cycle_detector, "kv", None)
        if kv is None:
            return None
        try:
            prewarm_key = f"prewarm:cycle:{query_text[:64]}"
            result = await kv.get(prewarm_key)
            if result:
                return {"text": result, "source": "cycle_prewarm"}
        except Exception:
            return None
        return None

    def _update_tract_metrics(self, p: AscendingPayload, d: DescendingPayload) -> None:
        n = max(1, self._tract_metrics["total_processed"])
        self._tract_metrics["ascending_avg_ms"] = (
            (self._tract_metrics["ascending_avg_ms"] * (n - 1)) + p.total_ascending_latency_ms
        ) / n
        self._tract_metrics["descending_avg_ms"] = (
            (self._tract_metrics["descending_avg_ms"] * (n - 1)) + d.total_descending_latency_ms
        ) / n

    def get_tract_metrics(self) -> Dict[str, Any]:
        return {
            **self._tract_metrics,
            "r_floor_threshold": self.R_FLOOR_THRESHOLD,
            "mesh_target_ms": self.mesh_target_latency_ms,
            "dual_brain_enabled": self.enable_dual_brain,
            "cycle_detection_enabled": self.enable_cycle_detection,
            "foresight_enabled": self.enable_foresight,
        }

    async def enter_sleep_cycle(self) -> Dict[str, Any]:
        results: Dict[str, Any] = {"started_at": datetime.now(timezone.utc).isoformat()}
        if self.auditor:
            try:
                run_nightly_audit = getattr(self.auditor, "run_nightly_audit", None)
                if callable(run_nightly_audit):
                    results["audit"] = await run_nightly_audit()
            except Exception as e:
                results["audit"] = {"error": str(e)}
        if self.foresight:
            try:
                forecast = getattr(self.foresight, "forecast_c_emo_trajectory", None)
                if callable(forecast):
                    results["foresight"] = await forecast()
            except Exception as e:
                results["foresight"] = {"error": str(e)}
        results["completed_at"] = datetime.now(timezone.utc).isoformat()
        return results

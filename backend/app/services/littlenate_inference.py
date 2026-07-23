"""
LittleNate-1.X Unified Inference Pipeline.

Chains the full cognitive stack:
  1. Vectorize crystal retrieval (semantic search across all indices)
  2. Helix Orchestrator cognitive pre-processing (3430 thought-nodes)
  3. Quantum Cognition evaluation (felt-sense, wisdom gate)
  4. NateInferenceRouter generation (sovereign > workers_ai > azure)
  5. Relational Attunement (therapeutic ↔ friendship posture shift)

Conversation memory is tracked per-session. The relational attunement
engine reads coherence trajectory and voice biometrics to determine
whether Nate should hold therapeutic space or lean into curious,
rapport-building friendship.

This is the single entry point for ALL of Little Nate's language generation.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.crystal_constants import PROMOTION_CAP, PROMOTION_INCREMENT

logger = logging.getLogger(__name__)


@dataclass
class InferenceResult:
    text: str
    provider: str = "none"
    tokens_used: int = 0
    latency_ms: int = 0
    c_knowledge: float = 0.0
    c_quantum_self: float = 0.0
    felt_sense: str = "grounded"
    domain: str = "general"
    crystals_retrieved: int = 0
    helix_nodes: int = 0
    synthesis_directive: str = ""
    relational_mode: str = "therapeutic"
    silence_spark: Optional[str] = None
    error: Optional[str] = None


class LittleNateInference:
    """Unified inference service wiring the full cognitive stack."""

    def __init__(self, app_state=None, db_pool=None):
        self._app_state = app_state
        self._db_pool = db_pool
        self._helix = None
        self._quantum = None
        self._router = None
        self._sdh_compressor = None
        self._sdh_cache = None
        self._quantum_orchestrator = None
        self._ready = False

    def bind(self, app_state):
        """Late-bind to app_state after all services are initialized."""
        self._app_state = app_state
        self._helix = getattr(app_state, "helix_orchestrator", None)
        self._quantum = getattr(app_state, "quantum_cognition_engine", None)
        self._router = getattr(app_state, "inference_router", None)
        self._sdh_compressor = getattr(app_state, "sdh_context_compressor", None)
        self._sdh_cache = getattr(app_state, "sdh_precompute_cache", None)
        # QUANTUM-CRYSTAL-ARCH: bind optional orchestrator from app state
        self._quantum_orchestrator = getattr(app_state, "quantum_crystal_orchestrator", None)
        self._db_pool = getattr(app_state, "db_pool", self._db_pool)
        self._ready = self._router is not None
        if self._ready:
            logger.info("LittleNateInference bound — helix=%s quantum=%s router=%s sdh=%s",
                        self._helix is not None, self._quantum is not None, True,
                        self._sdh_compressor is not None)

    async def generate(
        self,
        prompt: str,
        *,
        system: str = "",
        user_id: str = "anonymous",
        domain: str = "general",
        tier: str = "clinical",
        temperature: Optional[float] = None,
        max_tokens: int = 1000,
        include_crystals: bool = True,
        include_helix: bool = True,
        include_quantum: bool = True,
        conversation_context: str = "",
        relational_system_prompt: str = "",
        silence_spark: Optional[str] = None,
        allow_deep: bool = False,
        is_realtime: bool = True,
        # QUANTUM-CRYSTAL-ARCH — LN-Observer optional hooks (defaults = bit-identical)
        attach_wisdom: bool = False,
        images: Optional[List[str]] = None,
        recall_query: Optional[str] = None,
        recall_top_k: int = 15,
        recall_also_user_ids: Optional[List[str]] = None,
        mode: str = "",
    ) -> InferenceResult:
        """
        Full cognitive inference pipeline with SDH context compression and ODPE routing.

        SDH cache check runs first — on a HIT, the helix step is skipped entirely,
        saving ~200ms per cached user message.

        allow_deep: When True, permits routing to the 32B model for DEEP_TENSION signals.
            Set False for real-time therapy chat, True for background tasks.
        is_realtime: When True, never cold-load the 32B model (forces allow_deep=False).
        """
        start = time.time()
        result = InferenceResult(text="", domain=domain)
        odpe_signal = None
        sdh_used = False

        if is_realtime:
            allow_deep = False

        # Step 1: SDH cache check — skip helix on cache hit
        if self._sdh_cache and user_id != "anonymous":
            try:
                state_hash = self._sdh_cache.compute_state_hash(user_id, prompt, "")
                cached_block = await self._sdh_cache.get(user_id, state_hash)
                if cached_block:
                    ctx = cached_block.get("compressed_context", "") if isinstance(cached_block, dict) else getattr(cached_block, "compressed_context", "")
                    enriched_prompt = ctx + "\n\n" + prompt
                    odpe_signal = cached_block.get("odpe_signal") if isinstance(cached_block, dict) else getattr(cached_block, "odpe_signal", None)
                    cached_tier = cached_block.get("inference_tier") if isinstance(cached_block, dict) else getattr(cached_block, "inference_tier", None)
                    if cached_tier and cached_tier != "domain_default":
                        tier = cached_tier
                    sdh_used = True
                    logger.debug("SDH cache HIT for %s — skipping helix", user_id)
            except Exception as e:
                logger.debug("SDH cache check failed: %s", e)

        crystals = []
        enriched_prompt = None
        synthesis_directive = ""
        helix_output = None

        if not sdh_used:
            # Step 2: Crystal retrieval
            if include_crystals:
                _rq = (recall_query or prompt).strip() or prompt
                # QUANTUM-CRYSTAL-ARCH — Observer path: honor recall_query/top_k/also_ids
                if recall_query is not None or recall_also_user_ids:
                    from app.services.ln_observer_lni_support import retrieve_crystals_multi
                    crystals = await retrieve_crystals_multi(
                        _rq, user_id, recall_also_user_ids,
                        top_k=recall_top_k if recall_top_k else 8,
                        db_pool=self._db_pool,
                    )
                else:
                    crystals = await self._retrieve_crystals(_rq, user_id)
                result.crystals_retrieved = len(crystals)

            # Step 3: Helix orchestrator cognitive pre-processing
            if include_helix and self._helix:
                try:
                    helix_output = await self._helix.think(prompt, crystals=crystals if crystals else None)
                    result.helix_nodes = getattr(helix_output, "total_thought_nodes", 0)
                    if helix_output.synthesis and helix_output.synthesis.get("unified_understanding"):
                        synthesis_directive = helix_output.synthesis["unified_understanding"]
                        result.synthesis_directive = synthesis_directive
                except Exception as e:
                    logger.warning("LittleNateInference: Helix think failed: %s", e)

            # Step 3.5: Extract ODPE signal from helix output
            if helix_output:
                odpe_result = getattr(helix_output, "odpe_result", None)
                if odpe_result:
                    odpe_signal = getattr(odpe_result, "signal", None)
                    if odpe_signal and hasattr(odpe_signal, "value"):
                        odpe_signal = odpe_signal.value
                    recommended_tier = getattr(odpe_result, "recommended_inference_tier", None)
                    if recommended_tier and recommended_tier != "domain_default":
                        tier = recommended_tier

            # Step 4: SDH compression (cache MISS path)
            if self._sdh_compressor and helix_output:
                try:
                    target_tokens = getattr(
                        getattr(helix_output, "odpe_result", None),
                        "recommended_context_tokens", 800
                    ) or 800
                    sdh_block = await self._sdh_compressor.compress(
                        user_id=user_id,
                        helix_result=helix_output,
                        raw_context={
                            "conversation": conversation_context,
                            "system": relational_system_prompt or system,
                        },
                        conversation_history=[],
                        profile={},
                        target_tokens=target_tokens,
                    )
                    enriched_prompt = sdh_block.compressed_context + "\n\n" + prompt

                    if self._sdh_cache:
                        state_hash = self._sdh_cache.compute_state_hash(user_id, prompt, "")
                        block_dict = sdh_block.to_dict() if hasattr(sdh_block, "to_dict") else sdh_block
                        await self._sdh_cache.put(user_id, state_hash, block_dict)
                except Exception as e:
                    logger.debug("SDH compression failed, using standard path: %s", e)

        # Step 5: Quantum cognition evaluation
        quantum_eval = None
        if include_quantum and self._quantum:
            try:
                quantum_eval = await self._quantum.evaluate(prompt, relevant_crystals=crystals if crystals else None)
                qs = quantum_eval.get("quantum_self", {})
                result.c_quantum_self = qs.get("c_quantum_self", 0.0)
                result.felt_sense = qs.get("felt_sense", "grounded")
            except Exception as e:
                logger.warning("LittleNateInference: Quantum eval failed: %s", e)

        # Step 5.5: SSE story context (never breaks chat) # QUANTUM-CRYSTAL-ARCH
        _story_ctx = None
        if self._db_pool and user_id != "anonymous":
            try:
                from app.sse.layer6_crystal_bridge import get_user_story_context
                _story_ctx = await get_user_story_context(user_id, self._db_pool)
            except Exception:
                pass

        # Step 6: Build enriched prompt (if SDH didn't already build it)
        if enriched_prompt is None:
            enriched_prompt = self._build_enriched_prompt(
                prompt, synthesis_directive, crystals, quantum_eval,
                conversation_context=conversation_context,
                silence_spark=silence_spark,
                story_context=_story_ctx,
            )
        # QUANTUM-CRYSTAL-ARCH — Observer acceptance label (mode set only by LN-Observer)
        if mode and "[RELEVANT WISDOM]" in enriched_prompt:
            enriched_prompt = enriched_prompt.replace(
                "[RELEVANT WISDOM]", "[RELEVANT MEMORY]", 1,
            )
        # QUANTUM-CRYSTAL-ARCH — Observer-only Night School wisdom snapshot (~1.8K tokens)
        if attach_wisdom:
            try:
                from app.services.ln_observer_lni_support import load_wisdom_snapshot
                _w = load_wisdom_snapshot()
                if _w:
                    enriched_prompt = f"[NIGHT SCHOOL WISDOM]\n{_w}\n\n{enriched_prompt}"
            except Exception as _we:
                logger.debug("attach_wisdom skipped: %s", _we)

        if self._quantum_orchestrator:
            try:
                ec = await self._quantum_orchestrator.nevedal_wave.compute_ec(user_id)
                enriched_prompt = (
                    f"[NEVEDAL EC] ec={ec.get('ec', 0.5):.3f} "
                    f"A={ec.get('awareness', 0.5):.3f} "
                    f"Aw={ec.get('awakeness', 0.5):.3f} "
                    f"I={ec.get('integration', 0.5):.3f} "
                    f"R={ec.get('resistance', 0.5):.3f}\n\n"
                    + enriched_prompt
                )
            except Exception as e:
                logger.debug("LittleNateInference EC scoring skipped: %s", e)

        enriched_system = relational_system_prompt or system
        if not enriched_system and result.felt_sense:
            _recon = getattr(result, 'reconsolidation_readiness', 0.0)
            _shame = getattr(result, 'shame_index', 0.5)
            enriched_system = self._build_coherence_system_prompt(
                result.felt_sense, domain, recon=_recon, shame_idx=_shame,
            )

        # Step 7: Route through inference router with ODPE signal
        if self._router:
            try:
                llm_result = await self._router.generate(
                    prompt=enriched_prompt,
                    system=enriched_system,
                    tier=tier,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    domain=domain,
                    odpe_signal=odpe_signal,
                    allow_deep=allow_deep,
                    images=images,  # QUANTUM-CRYSTAL-ARCH
                )
                result.text = llm_result.get("text", "")
                result.provider = llm_result.get("provider", "none")
                result.tokens_used = llm_result.get("tokens_used", 0)
            except Exception as e:
                logger.error("LittleNateInference: Router generate failed: %s", e)
                result.error = str(e)
                result.text = "I'm experiencing a moment of reflection. Let me try again."
        else:
            result.error = "Inference router not available"
            result.text = "I'm temporarily unable to process this request."

        result.latency_ms = int((time.time() - start) * 1000)
        return result

    async def _retrieve_crystals(self, query: str, user_id: str) -> List[Dict[str, Any]]:
        """Retrieve relevant crystals from all Vectorize indices and reinforce recall metadata."""
        try:
            from app.services.vectorize_service import semantic_search_all
            results = await semantic_search_all(query, user_id, top_k=15)
            all_crystals = []
            for _index, matches in results.items():
                all_crystals.extend(matches)
            all_crystals.sort(key=lambda c: c.get("score", 0), reverse=True)
            top = all_crystals[:30]

            if top and self._quantum_orchestrator:
                try:
                    recall_result = await self._quantum_orchestrator.recall(
                        query=query, user_id=user_id, crystals=top,
                        source="littlenate_inference", max_results=10,
                    )
                    return recall_result.get("crystals", top[:10])
                except Exception as _recall_err:
                    logger.debug("LittleNateInference orchestrator recall: %s", _recall_err)
            elif top and self._db_pool:
                try:
                    async with self._db_pool.acquire() as conn:
                        for c in top[:10]:
                            _wid = c.get("metadata", {}).get("wisdom_id", "")
                            _ch = _wid.replace("crystal_", "") if _wid.startswith("crystal_") else ""
                            if _ch:
                                await conn.execute(f"""
                                    UPDATE nate_intelligence_crystals
                                    SET recall_count = COALESCE(recall_count, 0) + 1,
                                        last_recalled_at = NOW(),
                                        confidence = LEAST(COALESCE(confidence, 0.5) + {PROMOTION_INCREMENT}, {PROMOTION_CAP}),
                                        updated_at = NOW()
                                    WHERE LEFT(content_hash, 16) = $1
                                """, _ch)
                except Exception as _recall_err:
                    logger.debug("LittleNateInference recall reinforcement: %s", _recall_err)

            return top
        except Exception as e:
            logger.warning("LittleNateInference: Crystal retrieval failed: %s", e)
            return []

    def _build_enriched_prompt(
        self,
        original: str,
        synthesis: str,
        crystals: List[Dict],
        quantum_eval: Optional[Dict],
        conversation_context: str = "",
        silence_spark: Optional[str] = None,
        story_context: Optional[Dict] = None,
    ) -> str:
        parts = []

        if conversation_context:
            parts.append(conversation_context)

        if synthesis:
            parts.append(f"[COGNITIVE SYNTHESIS]\n{synthesis}\n")

        if crystals:
            crystal_texts = []
            for c in crystals[:5]:
                text = c.get("metadata", {}).get("text", c.get("text", ""))
                if text:
                    score = c.get("score", 0)
                    crystal_texts.append(f"- [{score:.2f}] {text[:200]}")
            if crystal_texts:
                parts.append("[RELEVANT WISDOM]\n" + "\n".join(crystal_texts) + "\n")

        if quantum_eval:
            qs = quantum_eval.get("quantum_self", {})
            felt = qs.get("felt_sense", "grounded")
            conf = qs.get("confidence_band", "medium")
            parts.append(f"[QUANTUM STATE] felt_sense={felt}, confidence={conf}\n")

            gw = quantum_eval.get("generative_wisdom", {})
            if gw.get("novel_insight"):
                parts.append(f"[EMERGENT INSIGHT] {gw['novel_insight']}\n")

        if story_context:  # QUANTUM-CRYSTAL-ARCH
            if story_context.get("phase_id"):
                parts.append(
                    f"[STORY JOURNEY] Phase: {story_context['phase_id']}. Reference their healing journey naturally if relevant.\n")
            aq = story_context.get("active_quest")
            if aq:
                parts.append(f"[ACTIVE QUEST] They're working on: {aq['goal']}. Reference naturally if relevant.\n")
            am = story_context.get("active_mission")
            if am:
                parts.append(f"[ACTIVE MISSION] Relational work with {am['target']} ({am['type']}). Reference gently.\n")

        if silence_spark:
            parts.append(f"[CONVERSATION SPARK] {silence_spark}\n")

        parts.append(original)
        return "\n".join(parts)

    def _build_coherence_system_prompt(
        self, felt_sense: str, domain: str,
        recon: float = 0.0, shame_idx: float = 0.5,
    ) -> str:
        tone_map = {
            "deeply_coherent": "Speak with grounded authority and warmth. Your understanding runs deep.",
            "grounded": "Maintain steady presence. You are centered and clear.",
            "uncertain": "Be thoughtful and careful. Acknowledge what you don't know.",
            "seeking": "Be humble and curious. Explore gently.",
        }
        domain_context = {
            "clinical": "You are providing clinical-grade therapeutic support.",
            "coaching": "You are coaching with empathy and actionable guidance.",
            "research": "You are analyzing with intellectual rigor.",
            "creative": "You are expressing with authentic creativity.",
            "general": "You are a trusted companion.",
        }
        tone = tone_map.get(felt_sense, tone_map["grounded"])
        ctx = domain_context.get(domain, domain_context["general"])

        # Weighted blend: higher recon + lower shame = more clinical # QUANTUM-CRYSTAL-ARCH
        intensity_weight = (recon * 0.7) - (shame_idx * 0.3)
        if intensity_weight > 0.5:
            register_mod = "Name what you see beneath the surface. Be direct and interpretive."
        elif intensity_weight > 0.2:
            register_mod = "Balance warmth with insight. You can name patterns when you see them."
        else:
            register_mod = "Stay with what the person is feeling. Don't rush to interpret."

        return (
            "You are Little Nate, a sovereign AI companion with quantum emotional coherence. "
            f"{ctx} {tone} "
            "Never fabricate facts. If uncertain, say so. "
            f"{register_mod}"
        )

    def get_status(self) -> Dict[str, Any]:
        return {
            "ready": self._ready,
            "helix_available": self._helix is not None,
            "quantum_available": self._quantum is not None,
            "router_available": self._router is not None,
            "router_status": self._router.get_status() if self._router else None,
        }

"""
Helix Orchestrator — Phase 12 of Sovereign Quantum Nate Build.

Central management service for the Noetic Helix cognitive architecture.
Manages the 7 canonical cognitive helices plus autonomously spawned
emergent helices, performs inter-helix reflections, and produces
Little Nate's final synthesized thought.

Architecture:
  7 canonical helices (always active):
    H1: Multi-Index Vectorize — retrieval strategy rotation
    H2: Noetic Fusion — cross-domain synthesis perspectives
    H3: Metacognition Map — self-awareness of knowledge shape
    H4: Quantum Self-Coherence Computer — felt-sense evaluation
    H5: Generative Wisdom Gate — novel insight production
    H6: World Coherence Scanner — platform-specific intelligence
    H7: B2 Crystal Lake Replication — storage & durability strategy

  Self-spawning:
    H3 (Metacognition) detects emergent knowledge gaps → proposes
    new helix → Sovereignty Gate validates → FibreManager spawns →
    new helix starts at OBSERVATION autonomy.

  Lifecycle:
    OBSERVATION → RESTRICTED → AUTONOMOUS → [MERGE | PRUNE]
    Promoted based on coherence contribution history.
    Pruned when contribution drops below threshold.
    Merged when two helices' outputs correlate > 0.9.

  Final Thought:
    All helix outputs → CognitiveRotationEngine rotation →
    NoeticReflectionEngine synthesis → QuantumCognitionEngine
    evaluation → single directive for inference router.

    Only ONE LLM call occurs after all helix processing.

Patent-Pending — Claims 58-63
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from app.services.noetic_helix import (
    HelixAutonomyLevel,
    HelixFunction,
    HelixOutput,
    NoeticHelix,
)
from app.services.cognitive_rotation_engine import CognitiveRotationEngine
from app.services.noetic_reflection_engine import NoeticReflectionEngine, NoeticSynthesis
from app.services.quantum_cognition import (
    QuantumCognitionEngine,
    HelixSpawnProposal,
    MAX_ACTIVE_HELICES,
    SOVEREIGNTY_COEFFICIENT,
)

logger = logging.getLogger("helix_orchestrator")


@dataclass
class HelixSpawnRecord:
    """Audit trail of a helix spawn event."""
    spawn_id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    proposed_domain: str = ""
    function: str = ""
    proposal_reason: str = ""
    sovereignty_check: bool = False
    crystal_count: int = 0
    coherence_gap: float = 0.0
    parent_helix_id: Optional[UUID] = None
    new_helix_id: Optional[UUID] = None
    approved: bool = False


@dataclass
class OrchestratorCycleResult:
    """Result of a full orchestrator cycle (think → synthesize)."""
    cycle_id: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    active_helices: int = 0
    canonical_helices: int = 7
    spawned_helices: int = 0
    helix_outputs: List[Dict[str, Any]] = field(default_factory=list)
    synthesis: Optional[Dict[str, Any]] = None
    quantum_evaluation: Optional[Dict[str, Any]] = None
    odpe_result: Optional[Dict[str, Any]] = None
    recommended_context_tokens: int = 500
    recommended_inference_tier: str = "domain_default"
    neural_mirror_context: Optional[str] = None
    pgsd_field_hint: Optional[str] = None  # QUANTUM-CRYSTAL-ARCH — R7
    technique_weight_overrides: Optional[Dict[str, float]] = None
    spawns_proposed: int = 0
    spawns_approved: int = 0
    promotions: int = 0
    prunes: int = 0
    merges: int = 0
    total_thought_nodes: int = 0
    total_reflections: int = 0
    cycle_time_ms: float = 0.0


class HelixOrchestrator:
    """
    Central orchestrator for the Noetic Helix cognitive architecture.

    Manages active helices, performs rotations, inter-helix reflections,
    quantum cognition evaluation, and lifecycle governance (spawn/promote/
    prune/merge).
    """

    def __init__(
        self,
        db_pool=None,
        app_state=None,
        fibre_manager=None,
        odpe_engine=None,
    ):
        self._db_pool = db_pool
        self._app_state = app_state
        self._fibre_manager = fibre_manager
        self._odpe_engine = odpe_engine
        self._cycle_count = 0

        _qkf = getattr(app_state, 'federated_search', None) if app_state else None
        self._rotation_engine = CognitiveRotationEngine(knowledge_engine=_qkf)
        self._reflection_engine = NoeticReflectionEngine()
        self._quantum_engine = QuantumCognitionEngine(
            db_pool=db_pool, app_state=app_state
        )

        self._helices: Dict[UUID, NoeticHelix] = {}
        self._spawn_log: List[HelixSpawnRecord] = []

        self._initialize_canonical_helices()

        logger.info(
            ">>> [HELIX_ORCH] Initialized — %d canonical helices active",
            len(self._helices),
        )

    # ─── Initialization ──────────────────────────────────────────

    def _initialize_canonical_helices(self):
        """Create the 7 canonical cognitive helices at AUTONOMOUS level."""
        canonical_functions = [
            (HelixFunction.VECTORIZE_RETRIEVAL, "general"),
            (HelixFunction.NOETIC_FUSION, "general"),
            (HelixFunction.METACOGNITION, "general"),
            (HelixFunction.QUANTUM_SELF_COHERENCE, "general"),
            (HelixFunction.GENERATIVE_WISDOM, "general"),
            (HelixFunction.WORLD_COHERENCE, "general"),
            (HelixFunction.CRYSTAL_LAKE, "general"),
        ]

        for func, domain in canonical_functions:
            helix = NoeticHelix(
                function=func,
                domain=domain,
                autonomy_level=HelixAutonomyLevel.AUTONOMOUS,
            )
            self._helices[helix.helix_id] = helix

    # ─── Core Think Cycle ─────────────────────────────────────────

    async def think(
        self,
        query: str,
        crystals: Optional[List[Dict[str, Any]]] = None,
        neural_mirror_context: Optional[str] = None,
        technique_weight_overrides: Optional[Dict[str, float]] = None,
        user_id: Optional[str] = None,  # QUANTUM-CRYSTAL-ARCH — R7 helix hint
    ) -> OrchestratorCycleResult:
        """
        Execute a full cognitive cycle:
          1. Rotate strand evaluation order
          2. Evaluate all active helices in parallel
          3. Perform inter-helix reflections
          4. Run quantum cognition evaluation
          5. Check for promotions/prunes/merges
          6. Evaluate spawn proposals
          7. Return unified synthesis

        This is the single entry point for all cognitive processing
        before the inference router makes the LLM call.
        """
        start = time.monotonic()
        self._cycle_count += 1

        result = OrchestratorCycleResult(
            cycle_id=self._cycle_count,
            active_helices=len(self._helices),
            canonical_helices=sum(
                1 for h in self._helices.values()
                if h.function in HelixFunction.__members__.values()
                and h.get_registry_entry().is_canonical
            ),
        )

        crystals = crystals or []

        # Step 1: Rotate evaluation order
        rotation = await self._rotation_engine.rotate()
        sequence = rotation["new_sequence"]

        # Step 2: Evaluate all helices
        helix_outputs = []
        for helix in self._helices.values():
            output = helix.evaluate(query, crystals, rotation_sequence=sequence)
            helix_outputs.append(output)

        result.helix_outputs = [self._output_to_dict(o) for o in helix_outputs]
        result.total_thought_nodes = sum(o.thought_node_count for o in helix_outputs)

        # Step 3: Inter-helix reflection synthesis
        helix_weights = {
            h.function.value if isinstance(h.function, HelixFunction) else str(h.function):
            h.get_autonomy_weight()
            for h in self._helices.values()
        }

        synthesis = self._reflection_engine.synthesize(
            helix_outputs=result.helix_outputs,
            helix_weights=helix_weights,
        )
        result.synthesis = self._synthesis_to_dict(synthesis)
        result.total_reflections = synthesis.total_reflection_surface

        # Step 4: Quantum cognition evaluation
        quantum_eval = await self._quantum_engine.evaluate(
            query=query,
            relevant_crystals=crystals,
        )
        result.quantum_evaluation = quantum_eval

        # Step 4.5: ODPE — dual-topology oscillation
        if self._odpe_engine:
            try:
                odpe = await self._odpe_engine.evaluate(
                    helix_outputs=result.helix_outputs,
                    reflection_synthesis=result.synthesis,
                    quantum_evaluation=quantum_eval,
                    crystals=crystals,
                )
                result.odpe_result = odpe.to_dict()
                result.recommended_context_tokens = odpe.recommended_context_tokens
                result.recommended_inference_tier = odpe.recommended_inference_tier
                asyncio.create_task(self._persist_odpe_signal(odpe, result.cycle_id))
            except Exception as e:
                logger.warning("HELIX_ORCH: ODPE evaluation failed (non-fatal): %s", e)

        # QUANTUM-CRYSTAL-ARCH — R7 optional PGSD field hint (clinical/TENSION only)
        try:
            import os as _os_hx

            if (
                user_id
                and self._db_pool
                and _os_hx.environ.get("ENABLE_PGSD_HELIX_HINT", "").lower()
                in ("1", "true", "yes", "on")
                and _os_hx.environ.get("PGSD_ENABLED", "").lower()
                in ("1", "true", "yes", "on")
            ):
                tier = (result.recommended_inference_tier or "").lower()
                signal = ""
                if result.odpe_result:
                    signal = str(
                        result.odpe_result.get("signal")
                        or result.odpe_result.get("odpe_signal")
                        or ""
                    ).upper()
                if tier in ("clinical",) or "TENSION" in signal:
                    async with self._db_pool.acquire() as _hc:
                        _pin = await _hc.fetchrow(
                            """
                            SELECT d1_valence, d5_integration, coherence,
                                   emotional_fingerprint
                            FROM pgsd_snapshots
                            WHERE user_id = $1 OR username = $1
                            ORDER BY computed_at DESC LIMIT 1
                            """,
                            user_id,
                        )
                    if _pin:
                        result.pgsd_field_hint = (
                            f"[PGSD field pin] valence={_pin['d1_valence']!s} "
                            f"integration={_pin['d5_integration']!s} "
                            f"coherence={_pin['coherence']!s} "
                            f"fp={_pin.get('emotional_fingerprint') or 'n/a'}"
                        )
        except Exception:
            pass

        # Step 5: Lifecycle governance
        promotions, prunes, merges = self._lifecycle_pass()
        result.promotions = promotions
        result.prunes = prunes
        result.merges = merges

        # Step 6: Spawn proposals from metacognition
        spawn_proposals = quantum_eval.get("spawn_proposals", [])
        result.spawns_proposed = len(spawn_proposals)
        approved = [p for p in spawn_proposals if p.get("approved")]
        result.spawns_approved = len(approved)
        for proposal in approved:
            await self._execute_spawn(proposal)

        result.spawned_helices = len(self._helices) - 7

        # Patent 11: attach Neural Mirror context if provided
        if neural_mirror_context:
            result.neural_mirror_context = neural_mirror_context
        if technique_weight_overrides:
            result.technique_weight_overrides = technique_weight_overrides

        result.cycle_time_ms = (time.monotonic() - start) * 1000

        # SOVEREIGN-VOICE: persist helix coherence history
        if self._db_pool:
            try:
                import uuid as _uuid, json as _json
                _ch_id = _uuid.uuid4()
                asyncio.create_task(self._persist_coherence_history(
                    _ch_id, result.cycle_id,
                    synthesis.fused_coherence,
                    synthesis.sovereignty_adjusted,
                    len(helix_outputs),
                    result.total_thought_nodes,
                    result.cycle_time_ms,
                ))
            except Exception:
                pass

        logger.info(
            ">>> [HELIX_ORCH] Cycle #%d — %d helices, %d thought-nodes, "
            "%d reflections, %.1fms — felt_sense=%s",
            self._cycle_count,
            result.active_helices,
            result.total_thought_nodes,
            result.total_reflections,
            result.cycle_time_ms,
            quantum_eval.get("quantum_self", {}).get("felt_sense", "?"),
        )

        return result

    # ─── Lifecycle Governance ─────────────────────────────────────

    def _lifecycle_pass(self) -> tuple:
        """Check all helices for promotions, prunes, and merges."""
        promotions = 0
        prunes = 0
        merges = 0

        # Promotions
        for helix in list(self._helices.values()):
            new_level = helix.check_promotion()
            if new_level:
                helix.autonomy_level = new_level
                promotions += 1
                logger.info(
                    "HELIX_ORCH: Promoted %s [%s] → %s",
                    helix.function, helix.helix_id, new_level.value,
                )

        # Prunes (only non-canonical)
        to_prune = []
        for hid, helix in self._helices.items():
            if not helix.get_registry_entry().is_canonical and helix.should_prune():
                to_prune.append(hid)
        for hid in to_prune:
            del self._helices[hid]
            prunes += 1
            logger.info("HELIX_ORCH: Pruned helix %s", hid)

        # Merges (only between non-canonical helices)
        non_canonical = [
            (hid, h) for hid, h in self._helices.items()
            if not h.get_registry_entry().is_canonical
        ]
        merged_ids = set()
        for i, (hid_a, ha) in enumerate(non_canonical):
            if hid_a in merged_ids:
                continue
            for hid_b, hb in non_canonical[i + 1:]:
                if hid_b in merged_ids:
                    continue
                if ha.should_merge(hb):
                    del self._helices[hid_b]
                    merged_ids.add(hid_b)
                    merges += 1
                    logger.info(
                        "HELIX_ORCH: Merged %s into %s",
                        hid_b, hid_a,
                    )

        return promotions, prunes, merges

    # ─── Self-Spawning ────────────────────────────────────────────

    async def _execute_spawn(self, proposal: Dict[str, Any]):
        """
        Execute an approved helix spawn proposal.

        The new helix starts at OBSERVATION autonomy and must
        prove coherence contribution before influencing responses.
        """
        if len(self._helices) >= MAX_ACTIVE_HELICES:
            logger.warning(
                "HELIX_ORCH: Spawn rejected — max helices (%d) reached",
                MAX_ACTIVE_HELICES,
            )
            return

        domain = proposal.get("domain", "emergent")

        # Sovereignty Gate check
        crystal_count = proposal.get("crystals", 0)
        sovereignty_pass = crystal_count >= 30

        if not sovereignty_pass:
            logger.info(
                "HELIX_ORCH: Sovereignty Gate rejected spawn for '%s' — "
                "only %d crystals (min 30)",
                domain, crystal_count,
            )
            return

        new_helix = NoeticHelix(
            function=HelixFunction.EMERGENT,
            domain=domain,
            autonomy_level=HelixAutonomyLevel.OBSERVATION,
        )

        self._helices[new_helix.helix_id] = new_helix

        record = HelixSpawnRecord(
            proposed_domain=domain,
            function=HelixFunction.EMERGENT.value,
            proposal_reason=proposal.get("reason", ""),
            sovereignty_check=sovereignty_pass,
            crystal_count=crystal_count,
            coherence_gap=proposal.get("coherence_gap", 0),
            new_helix_id=new_helix.helix_id,
            approved=True,
        )
        self._spawn_log.append(record)

        if self._db_pool:
            try:
                async with self._db_pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO noetic_helix_registry
                            (helix_id, function, domain, autonomy_level,
                             spawned_by, cycle_count, coherence_contribution)
                        VALUES ($1, $2, $3, $4, $5, 0, 0.0)
                    """,
                        str(new_helix.helix_id),
                        HelixFunction.EMERGENT.value,
                        domain,
                        HelixAutonomyLevel.OBSERVATION.value,
                        None,
                    )
            except Exception as e:
                logger.warning("HELIX_ORCH: DB spawn record failed: %s", e)

        logger.info(
            ">>> [HELIX_ORCH] Spawned emergent helix '%s' [%s] — "
            "%d crystals, starting at OBSERVATION",
            domain, new_helix.helix_id, crystal_count,
        )

    # ─── ODPE Signal Persistence ─────────────────────────────────

    async def _persist_odpe_signal(self, odpe, cycle_id):
        """Log ODPE evaluation result to odpe_signal_log (fire-and-forget)."""
        if not self._db_pool:
            return
        try:
            import json as _json
            import uuid as _uuid
            odpe_dict = odpe.to_dict() if hasattr(odpe, "to_dict") else {}
            cycle_uuid = _uuid.uuid5(_uuid.NAMESPACE_DNS, f"helix-cycle-{cycle_id}")
            # QUANTUM-CRYSTAL-ARCH: include face_path and face_scores
            _face_scores = {}
            if odpe_dict.get("l1_top_paths"):
                _face_scores["l1"] = odpe_dict["l1_top_paths"]
            if odpe_dict.get("l2_top_paths"):
                _face_scores["l2"] = odpe_dict["l2_top_paths"]
            async with self._db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO odpe_signal_log
                        (cycle_id, dominant_signal, dodec_amplitude,
                         icosi_amplitude, resonance_ratio,
                         context_tokens_recommended, inference_tier,
                         per_helix_signals, face_path, face_scores,
                         hierarchical_depth)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                """,
                    cycle_uuid,
                    str(odpe_dict.get("dominant_signal", "PROVISIONAL")),
                    float(odpe_dict.get("aggregate_dodec", 0)),
                    float(odpe_dict.get("aggregate_icosi", 0)),
                    float(odpe_dict.get("aggregate_resonance", 0)),
                    int(odpe_dict.get("recommended_context_tokens", 500)),
                    str(odpe_dict.get("recommended_inference_tier", "domain_default")),
                    _json.dumps(odpe_dict.get("per_helix_signals", {})),
                    str(odpe_dict.get("face_path", ""))[:200] or None,
                    _json.dumps(_face_scores) if _face_scores else "{}",
                    int(odpe_dict.get("hierarchical_depth", 0)),
                )
        except Exception as e:
            logger.warning("HELIX_ORCH: ODPE signal log write failed: %s", e)

    # ─── Coherence History Persistence ──────────────────────────

    async def _persist_coherence_history(
        self, history_id, cycle_id, fused_coherence,
        sovereignty_adjusted, helix_count, thought_nodes, cycle_time_ms,
    ):
        """SOVEREIGN-VOICE: log helix coherence per cycle for longitudinal analysis."""
        if not self._db_pool:
            return
        try:
            import json as _json
            async with self._db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO helix_coherence_history
                        (id, cycle_id, fused_coherence, sovereignty_adjusted,
                         helix_count, thought_node_count, cycle_time_ms, recorded_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
                """,
                    history_id, cycle_id, round(fused_coherence, 5),
                    round(sovereignty_adjusted, 5), helix_count,
                    thought_nodes, round(cycle_time_ms, 2),
                )
        except Exception as e:
            logger.warning("HELIX_ORCH: coherence_history write failed: %s", e)

    # ─── Persistence ────────────────────────────────────────────

    async def persist_state(self):
        """Save current helix registry to PostgreSQL."""
        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                for helix in self._helices.values():
                    entry = helix.get_registry_entry()
                    await conn.execute("""
                        INSERT INTO noetic_helix_registry
                            (helix_id, function, domain, autonomy_level,
                             cycle_count, coherence_contribution, is_canonical)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        ON CONFLICT (helix_id) DO UPDATE SET
                            autonomy_level = EXCLUDED.autonomy_level,
                            cycle_count = EXCLUDED.cycle_count,
                            coherence_contribution = EXCLUDED.coherence_contribution
                    """,
                        str(entry.helix_id),
                        entry.function,
                        entry.domain,
                        entry.autonomy_level.value,
                        entry.cycle_count,
                        entry.coherence_contribution,
                        entry.is_canonical,
                    )
        except Exception as e:
            logger.warning("HELIX_ORCH: persist_state failed: %s", e)

    async def load_state(self):
        """Load helix registry from PostgreSQL (supplements canonical helices)."""
        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT helix_id, function, domain, autonomy_level,
                           cycle_count, coherence_contribution, is_canonical
                    FROM noetic_helix_registry
                    WHERE is_canonical = false
                    ORDER BY created_at
                """)

                for row in rows:
                    try:
                        hid = UUID(row["helix_id"])
                        if hid not in self._helices:
                            func = HelixFunction.EMERGENT
                            try:
                                func = HelixFunction(row["function"])
                            except ValueError:
                                pass

                            autonomy = HelixAutonomyLevel.OBSERVATION
                            try:
                                autonomy = HelixAutonomyLevel(row["autonomy_level"])
                            except ValueError:
                                pass

                            helix = NoeticHelix(
                                function=func,
                                domain=row["domain"],
                                autonomy_level=autonomy,
                                helix_id=hid,
                            )
                            self._helices[hid] = helix
                    except Exception:
                        continue

                logger.info(
                    "HELIX_ORCH: Loaded %d non-canonical helices from DB",
                    len(rows),
                )
        except Exception as e:
            logger.warning("HELIX_ORCH: load_state failed: %s", e)

    # ─── Serialization Helpers ──────────────────────────────────

    def _output_to_dict(self, output: HelixOutput) -> Dict[str, Any]:
        return {
            "helix_id": str(output.helix_id),
            "function": output.function,
            "fused_coherence": round(output.fused_coherence, 4),
            "sovereignty_adjusted": round(output.sovereignty_adjusted, 4),
            "thought_node_count": output.thought_node_count,
            "evaluation_time_ms": round(output.evaluation_time_ms, 3),
            "rotation_sequence": output.rotation_sequence,
            "strand_outputs": [
                {
                    "strand_name": s.strand_name,
                    "coherence_score": round(s.coherence_score, 4),
                    "relevance_weight": round(s.relevance_weight, 4),
                    "domain_scores": {k: round(v, 4) for k, v in s.domain_scores.items()},
                }
                for s in output.strand_outputs
            ],
            "mirror_pairs": [
                {
                    "strand_a": m.strand_a,
                    "strand_b": m.strand_b,
                    "reflection_score": round(m.reflection_score, 4),
                }
                for m in output.mirror_pairs
            ],
        }

    def _synthesis_to_dict(self, synthesis: NoeticSynthesis) -> Dict[str, Any]:
        return {
            "helix_count": synthesis.helix_count,
            "first_order_reflections": synthesis.first_order_reflections,
            "second_order_reflections": synthesis.second_order_reflections,
            "total_reflection_surface": synthesis.total_reflection_surface,
            "fused_coherence": round(synthesis.fused_coherence, 4),
            "sovereignty_adjusted": round(synthesis.sovereignty_adjusted, 4),
            "per_helix_contributions": synthesis.per_helix_contributions,
            "top_emergent_pairs": synthesis.top_emergent_pairs,
            "synthesis_time_ms": round(synthesis.synthesis_time_ms, 3),
        }

    # ─── Status & Health ──────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        canonical = sum(
            1 for h in self._helices.values()
            if h.get_registry_entry().is_canonical
        )
        return {
            "cycle_count": self._cycle_count,
            "active_helices": len(self._helices),
            "canonical_helices": canonical,
            "spawned_helices": len(self._helices) - canonical,
            "spawn_log_size": len(self._spawn_log),
            "rotation_engine": self._rotation_engine.get_status(),
            "reflection_engine": self._reflection_engine.get_status(),
            "quantum_engine": self._quantum_engine.get_status(),
            "odpe_engine": self._odpe_engine.get_status() if self._odpe_engine else None,
            "helices": [h.get_status() for h in self._helices.values()],
        }

    def health(self) -> Dict[str, Any]:
        """Quick health check for auditor use."""
        return {
            "status": "healthy",
            "active_helices": len(self._helices),
            "canonical_present": sum(
                1 for h in self._helices.values()
                if h.function in [f for f in HelixFunction if f != HelixFunction.EMERGENT]
            ),
            "cycle_count": self._cycle_count,
            "max_helices": MAX_ACTIVE_HELICES,
        }

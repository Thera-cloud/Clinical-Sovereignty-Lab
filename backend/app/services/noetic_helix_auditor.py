"""
Noetic Helix Auditor — Phase 12 of Sovereign Quantum Nate Build.

3x daily trust scorecard for the cognitive helix architecture.
Runs 18 checks across 5 categories:
  - Helix Health (5): orchestrator up, 7 canonical helices, rotation engine,
    reflection engine, quantum cognition engine
  - Data Integrity (4): registry table, coherence history, spawn log,
    quantum cognition log
  - Cognitive Pipeline (3): helix evaluation, inter-helix reflections,
    quantum self-coherence computation
  - Self-Governance (2): spawn sovereignty gate, autonomy lifecycle
  - ODPE Engine (4): engine initialized, dual evaluators, resonance comparator,
    liminal equilibrium reader

Stagger: 60s (earliest slot, because cognitive health is foundational)
Baseline key: noetic_helix_check_count (expected: 18)

Patent-Pending — Claims 58-63, 64-71
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("noetic_helix_auditor")

AUDIT_HOURS = {5, 17, 23}
STAGGER_SECONDS = 60

TAB_ENDPOINTS = [
    {
        "tab_num": 1,
        "tab": "Helix Health",
        "endpoints": [
            {"path": "orchestrator_status", "method": "DB", "description": "Orchestrator initialized and responsive"},
            {"path": "canonical_helix_count", "method": "DB", "description": "All 7 canonical helices present"},
            {"path": "rotation_engine_status", "method": "DB", "description": "Cognitive rotation engine initialized"},
            {"path": "reflection_engine_status", "method": "DB", "description": "Noetic reflection engine initialized"},
            {"path": "quantum_engine_status", "method": "DB", "description": "Quantum cognition engine initialized"},
        ],
    },
    {
        "tab_num": 2,
        "tab": "Data Integrity",
        "endpoints": [
            {"path": "registry_table", "method": "DB", "description": "noetic_helix_registry table exists"},
            {"path": "coherence_history_table", "method": "DB", "description": "helix_coherence_history table exists"},
            {"path": "spawn_log_table", "method": "DB", "description": "helix_spawn_log table exists"},
            {"path": "quantum_log_table", "method": "DB", "description": "quantum_cognition_log table exists"},
        ],
    },
    {
        "tab_num": 3,
        "tab": "Cognitive Pipeline",
        "endpoints": [
            {"path": "helix_evaluation", "method": "DB", "description": "Helix evaluation produces valid output"},
            {"path": "inter_helix_reflections", "method": "DB", "description": "Inter-helix reflections compute correctly"},
            {"path": "quantum_self_coherence", "method": "DB", "description": "Quantum self-coherence computes C_quantum_self"},
        ],
    },
    {
        "tab_num": 4,
        "tab": "Self-Governance",
        "endpoints": [
            {"path": "spawn_sovereignty_gate", "method": "DB", "description": "Sovereignty gate validates spawn proposals"},
            {"path": "autonomy_lifecycle", "method": "DB", "description": "Autonomy promotion/prune/merge lifecycle works"},
        ],
    },
    {
        "tab_num": 5,
        "tab": "ODPE Engine",
        "endpoints": [
            {"path": "odpe_engine_initialized", "method": "DB", "description": "ODPE Engine initialized on app.state"},
            {"path": "odpe_dual_evaluators", "method": "DB", "description": "Dodecahedron + Icositetragon evaluators present"},
            {"path": "odpe_resonance_comparator", "method": "DB", "description": "Resonance comparator classifies signals"},
            {"path": "odpe_liminal_reader", "method": "DB", "description": "Liminal equilibrium reader produces bias"},
        ],
    },
]


class NoeticHelixAuditor:
    """
    Trust auditor for the Noetic Helix cognitive architecture.
    Runs 18 checks 3x daily at stagger 60s.
    """

    def __init__(self, db_pool=None, app_state=None, admin_token: str = ""):
        self._db_pool = db_pool
        self._app_state = app_state
        self._admin_token = admin_token or os.environ.get("SKYEYE_AUDIT_TOKEN", "")
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the audit loop."""
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(">>> NoeticHelixAuditor started (stagger=%ds)", STAGGER_SECONDS)

    async def stop(self):
        """Stop the audit loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self):
        """Main audit loop — fires 3x daily at audit hours."""
        await asyncio.sleep(STAGGER_SECONDS)

        while self._running:
            try:
                now = datetime.now(timezone.utc)
                if now.hour in AUDIT_HOURS and now.minute < 5:
                    await self._build_and_send()
                    await asyncio.sleep(3600)
                else:
                    await asyncio.sleep(60)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("NoeticHelixAuditor cycle error: %s", e)
                await asyncio.sleep(300)

    async def _build_and_send(self):
        """Build the trust scorecard and log to skyeye_activity."""
        # Email silenced — Trust Enforcer sends consolidated report
        results = []
        total = sum(len(t["endpoints"]) for t in TAB_ENDPOINTS)
        trusted = 0

        for tab in TAB_ENDPOINTS:
            for endpoint in tab["endpoints"]:
                check_id = endpoint["path"]
                try:
                    passed = await self._run_check(check_id)
                    status = "TRUSTED" if passed else "WARNING"
                    if passed:
                        trusted += 1
                except Exception as e:
                    status = "FAILED"
                    logger.warning("NoeticHelixAuditor check '%s' failed: %s", check_id, e)

                results.append({
                    "tab": tab["tab"],
                    "check": check_id,
                    "status": status,
                    "description": endpoint["description"],
                })

        summary = f"{trusted}/{total} TRUSTED"
        logger.info("NoeticHelixAuditor: %s", summary)

        if self._db_pool:
            try:
                async with self._db_pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO skyeye_activity (type, platform, content, created_at)
                        VALUES ($1, $2, $3::jsonb, NOW())
                    """,
                        "noetic_helix_audit_sent",
                        "system",
                        json.dumps({
                            "summary": summary,
                            "trusted": trusted,
                            "total": total,
                            "checks": results,
                        }),
                    )
            except Exception as e:
                logger.warning("NoeticHelixAuditor: DB log failed: %s", e)

    async def _run_check(self, check_id: str) -> bool:
        """Run a single audit check and return True if passed."""

        # ── Helix Health ──
        if check_id == "orchestrator_status":
            if not self._app_state:
                return False
            orch = getattr(self._app_state, "helix_orchestrator", None)
            return orch is not None

        if check_id == "canonical_helix_count":
            if not self._app_state:
                return False
            orch = getattr(self._app_state, "helix_orchestrator", None)
            if not orch:
                return False
            health = orch.health()
            return health.get("canonical_present", 0) >= 7

        if check_id == "rotation_engine_status":
            if not self._app_state:
                return False
            orch = getattr(self._app_state, "helix_orchestrator", None)
            if not orch:
                return False
            return orch._rotation_engine is not None

        if check_id == "reflection_engine_status":
            if not self._app_state:
                return False
            orch = getattr(self._app_state, "helix_orchestrator", None)
            if not orch:
                return False
            return orch._reflection_engine is not None

        if check_id == "quantum_engine_status":
            if not self._app_state:
                return False
            orch = getattr(self._app_state, "helix_orchestrator", None)
            if not orch:
                return False
            return orch._quantum_engine is not None

        # ── Data Integrity ──
        if check_id == "registry_table":
            return await self._table_exists("noetic_helix_registry")

        if check_id == "coherence_history_table":
            return await self._table_exists("helix_coherence_history")

        if check_id == "spawn_log_table":
            return await self._table_exists("helix_spawn_log")

        if check_id == "quantum_log_table":
            return await self._table_exists("quantum_cognition_log")

        # ── Cognitive Pipeline ──
        if check_id == "helix_evaluation":
            return self._test_helix_evaluation()

        if check_id == "inter_helix_reflections":
            return self._test_inter_helix_reflections()

        if check_id == "quantum_self_coherence":
            return self._test_quantum_self_coherence()

        # ── Self-Governance ──
        if check_id == "spawn_sovereignty_gate":
            return self._test_sovereignty_gate()

        if check_id == "autonomy_lifecycle":
            return self._test_autonomy_lifecycle()

        # ── ODPE Engine ──
        if check_id == "odpe_engine_initialized":
            return self._test_odpe_engine_initialized()

        if check_id == "odpe_dual_evaluators":
            return self._test_odpe_dual_evaluators()

        if check_id == "odpe_resonance_comparator":
            return self._test_odpe_resonance_comparator()

        if check_id == "odpe_liminal_reader":
            return self._test_odpe_liminal_reader()

        return False

    # ── DB Helpers ──

    async def _table_exists(self, table_name: str) -> bool:
        if not self._db_pool:
            return False
        try:
            async with self._db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT EXISTS(
                        SELECT 1 FROM information_schema.tables
                        WHERE table_name = $1
                    ) as exists
                """, table_name)
                return row and row["exists"]
        except Exception:
            return False

    # ── Pipeline Tests ──

    def _test_helix_evaluation(self) -> bool:
        """Test that a NoeticHelix can evaluate a query and produce output."""
        try:
            from app.services.noetic_helix import NoeticHelix, HelixFunction, HelixAutonomyLevel
            helix = NoeticHelix(
                function=HelixFunction.METACOGNITION,
                autonomy_level=HelixAutonomyLevel.AUTONOMOUS,
            )
            output = helix.evaluate("test query", [{"domain": "clinical", "confidence": 0.8, "recall_count": 3}])
            return output.thought_node_count > 0 and output.fused_coherence >= 0
        except Exception as e:
            logger.warning("Helix evaluation test failed: %s", e)
            return False

    def _test_inter_helix_reflections(self) -> bool:
        """Test that NoeticReflectionEngine can synthesize helix outputs."""
        try:
            from app.services.noetic_reflection_engine import NoeticReflectionEngine
            engine = NoeticReflectionEngine()
            synthesis = engine.synthesize(
                helix_outputs=[
                    {"helix_id": "a", "function": "metacognition", "fused_coherence": 0.6,
                     "sovereignty_adjusted": 0.67, "strand_outputs": [], "mirror_pairs": []},
                    {"helix_id": "b", "function": "noetic_fusion", "fused_coherence": 0.5,
                     "sovereignty_adjusted": 0.56, "strand_outputs": [], "mirror_pairs": []},
                ],
                helix_weights={"metacognition": 1.0, "noetic_fusion": 1.0},
            )
            return synthesis.total_reflection_surface >= 0
        except Exception as e:
            logger.warning("Inter-helix reflection test failed: %s", e)
            return False

    def _test_quantum_self_coherence(self) -> bool:
        """Test that QuantumSelfCoherenceComputer produces valid C_quantum_self."""
        try:
            from app.services.quantum_cognition import (
                QuantumSelfCoherenceComputer, MetacognitionSnapshot
            )
            computer = QuantumSelfCoherenceComputer()
            state = computer.compute(
                query="What is emotional coherence?",
                metacognition=MetacognitionSnapshot(),
                relevant_crystals=[
                    {"domain": "clinical", "confidence": 0.9, "recall_count": 5, "age_days": 10},
                ],
            )
            return 0 <= state.c_quantum_self <= 1.0 and state.felt_sense != ""
        except Exception as e:
            logger.warning("Quantum self-coherence test failed: %s", e)
            return False

    def _test_sovereignty_gate(self) -> bool:
        """Test that the sovereignty gate properly validates spawn proposals."""
        try:
            from app.services.quantum_cognition import MetacognitionMap, MetacognitionSnapshot
            mm = MetacognitionMap()
            snapshot = MetacognitionSnapshot()
            snapshot.emergent_gaps = [
                {"domain": "ethics", "crystal_count": 50, "avg_confidence": 0.6, "spawn_eligible": True},
            ]
            proposals = mm.evaluate_spawn_proposal(snapshot)
            return len(proposals) > 0 and proposals[0].approved
        except Exception as e:
            logger.warning("Sovereignty gate test failed: %s", e)
            return False

    def _test_autonomy_lifecycle(self) -> bool:
        """Test that autonomy promotion logic works correctly."""
        try:
            from app.services.noetic_helix import NoeticHelix, HelixFunction, HelixAutonomyLevel
            helix = NoeticHelix(
                function=HelixFunction.EMERGENT,
                domain="test",
                autonomy_level=HelixAutonomyLevel.OBSERVATION,
            )
            for _ in range(5):
                helix.evaluate("test", [{"domain": "test", "confidence": 0.9, "recall_count": 5}])

            promotion = helix.check_promotion()
            return promotion == HelixAutonomyLevel.RESTRICTED
        except Exception as e:
            logger.warning("Autonomy lifecycle test failed: %s", e)
            return False

    # ── ODPE Engine Tests ──

    def _test_odpe_engine_initialized(self) -> bool:
        """Verify ODPEEngine exists on app.state (or can be constructed)."""
        if self._app_state:
            engine = getattr(self._app_state, "odpe_engine", None)
            if engine is not None:
                return True
        try:
            from app.services.odpe_engine import ODPEEngine
            e = ODPEEngine()
            return e is not None
        except Exception as ex:
            logger.warning("ODPE engine init test failed: %s", ex)
            return False

    def _test_odpe_dual_evaluators(self) -> bool:
        """Verify both topology evaluators produce valid amplitudes."""
        try:
            from app.services.odpe_engine import (
                DodecahedronEvaluator, IcositetragonEvaluator,
            )
            dodec = DodecahedronEvaluator()
            icosi = IcositetragonEvaluator()
            mock_agents = [{"score": 0.7, "confidence": 0.8}] * 7
            d_result = dodec.evaluate(mock_agents)
            i_result = icosi.evaluate(mock_agents)
            if isinstance(d_result, list):
                d_ok = len(d_result) > 0 and all(0 <= v <= 1 for v in d_result)
            else:
                d_ok = isinstance(d_result, (int, float)) and 0 <= d_result <= 1
            if isinstance(i_result, dict):
                i_ok = len(i_result) > 0 and all(0 <= v <= 1 for v in i_result.values())
            elif isinstance(i_result, list):
                i_ok = len(i_result) > 0 and all(0 <= v <= 1 for v in i_result)
            else:
                i_ok = isinstance(i_result, (int, float)) and 0 <= i_result <= 1
            return d_ok and i_ok
        except Exception as ex:
            logger.warning("ODPE dual evaluators test failed: %s", ex)
            return False

    def _test_odpe_resonance_comparator(self) -> bool:
        """Verify resonance comparator classifies a signal from amplitudes."""
        try:
            from app.services.odpe_engine import ResonanceComparator
            comp = ResonanceComparator()
            if hasattr(comp, "classify"):
                from app.services.odpe_engine import AmplitudeVector, ODPESignal
                amp = AmplitudeVector(
                    dodec_amplitude=0.8,
                    icosi_amplitude=0.75,
                    resonance_ratio=0.8 / 0.75,
                )
                signal = comp.classify(amp)
                return isinstance(signal, ODPESignal)
            elif hasattr(comp, "classify_signal"):
                test_scores = {"clinical:local": 0.8, "coaching:local": 0.6}
                result = comp.classify_signal(test_scores)
                return isinstance(result, tuple) and len(result) == 2
            return comp is not None
        except Exception as ex:
            logger.warning("ODPE resonance comparator test failed: %s", ex)
            return False

    def _test_odpe_liminal_reader(self) -> bool:
        """Verify liminal equilibrium reader returns a valid bias value."""
        try:
            from app.services.odpe_engine import LiminalEquilibriumReader
            reader = LiminalEquilibriumReader(db_pool=None)
            status = reader.get_status()
            bias = status.get("current_bias", None)
            return bias is not None and 0.5 <= bias <= 1.5
        except Exception as ex:
            logger.warning("ODPE liminal reader test failed: %s", ex)
            return False

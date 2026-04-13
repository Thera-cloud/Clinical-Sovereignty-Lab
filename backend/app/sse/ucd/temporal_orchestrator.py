"""Temporal Orchestrator — replaces schedule-driven generation with event-driven.

Receives TMC-classified moments and dispatches CreativeDirectives to the
appropriate generation pipeline. The Temporal Orchestrator is the central
conductor of the UCD loop (Section 6 of SS-UCD-001).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .creative_directive import CreativeDirective, log_directive
from .tmc import TherapeuticMomentClassifier
from .modality_selector import ModalitySelector
from .intensity_governor import IntensityGovernor
from .narrative_coherence import NarrativeCoherenceEnforcer

logger = logging.getLogger(__name__)


class TemporalOrchestrator:
    """Orchestrate the UCD loop: classify → select → govern → direct → generate.

    This is the Phase 4 entry point. Earlier phases can use individual
    subsystems directly; the orchestrator wires them together.
    """

    def __init__(self, db_pool):
        self.db_pool = db_pool
        self.tmc = TherapeuticMomentClassifier(db_pool)
        self.modality_selector = ModalitySelector(db_pool)
        self.intensity_governor = IntensityGovernor(db_pool)
        self.nce = NarrativeCoherenceEnforcer(db_pool)

    async def evaluate_and_dispatch(
        self,
        user_id: str,
        nso: Optional[dict] = None,
        trigger: str = "event_hook",
    ) -> Optional[CreativeDirective]:
        """Full UCD loop: TMC → Modality → Intensity → NCE → Directive.

        Returns None if the moment class is REST or safety gates block.
        """
        classification = await self.tmc.classify(user_id)
        moment_class = classification["moment_class"]

        if moment_class == "REST":
            logger.debug("TMC classified REST for %s — no generation", user_id)
            return None

        engagement_history = await self.modality_selector.get_engagement_history(user_id)
        deployment_ctx = (
            nso.get("state", {}).get("deployment_context", "private")
            if nso else "private"
        )
        safety_gate = classification.get("safety_gate", {})
        gate_modality_restrictions = safety_gate.get("modality_restrictions", [])
        modality_result = await self.modality_selector.select(
            user_id, moment_class, deployment_ctx, engagement_history,
            additional_blocked=gate_modality_restrictions,
        )
        selected_modality = modality_result["selected_modality"]

        proposed_intensity = self._estimate_intensity(classification)
        intensity_result = await self.intensity_governor.check_and_record(
            user_id, moment_class, proposed_intensity,
        )

        coherence_ctx = await self.nce.build_coherence_context(user_id, nso)

        directive = CreativeDirective(
            directive_id=str(uuid.uuid4()),
            user_id=user_id,
            moment_class=moment_class,
            selected_modality=selected_modality,
            intensity=intensity_result["recorded_intensity"],
            coherence_context=coherence_ctx,
            nso_snapshot=nso.get("state", {}) if nso else {},
            trigger=trigger,
            tmc_confidence=classification["confidence"],
            safety_gate=classification.get("safety_gate", {}),
        )

        if self.db_pool:
            try:
                await log_directive(directive, self.db_pool)
            except Exception as e:
                logger.warning("Failed to log directive: %s", e)

        if directive and trigger != "dry_run":
            await self._dispatch_to_pipeline(user_id, directive)

        return directive

    async def _dispatch_to_pipeline(
        self,
        user_id: str,
        directive: CreativeDirective,
    ) -> None:
        """Hand the directive to the SSE delivery runtime for actual generation."""
        try:
            from app.sse.foundation import delivery_runtime as dr
            gen_result = await dr.generate_from_directive(
                user_id,
                directive.__dict__,
                self.db_pool,
            )
            if gen_result and gen_result.get("generation_id"):
                await self.nce.update_nso_after_generation(
                    user_id,
                    gen_result["generation_id"],
                    directive.__dict__,
                )
                from .creative_directive import mark_directive_executed
                await mark_directive_executed(directive.directive_id, self.db_pool)
                logger.info(
                    "UCD dispatch complete: %s/%s → gen %s",
                    user_id, directive.moment_class,
                    gen_result["generation_id"],
                )
        except Exception as e:
            logger.warning("UCD pipeline dispatch failed for %s: %s", user_id, e)

    def _estimate_intensity(self, classification: dict) -> float:
        """Derive a proposed intensity from TMC signals."""
        moment = classification.get("moment_class", "REST")
        confidence = classification.get("confidence", 0.5)

        base_intensities = {
            "CRISIS": 0.9,
            "BREAKTHROUGH": 0.75,
            "HERITAGE": 0.7,
            "RECURRENCE": 0.6,
            "THRESHOLD": 0.5,
            "INTEGRATION": 0.4,
            "REST": 0.2,
        }

        base = base_intensities.get(moment, 0.4)
        return round(min(1.0, base * (0.7 + 0.3 * confidence)), 4)

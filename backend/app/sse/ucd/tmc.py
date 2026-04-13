"""Therapeutic Moment Classifier (TMC) — Phase 2 rule-based classifier.

Classifies the current therapeutic moment into one of seven classes using
weighted signals from Section 7.2 of SS-UCD-001. Replaces schedule-driven
generation with moment-driven generation.

Phase 5 replaces this with a trained logistic regression model; the rule-based
classifier remains as a fallback if model accuracy drops below threshold.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)

MOMENT_CLASSES = (
    "THRESHOLD", "BREAKTHROUGH", "INTEGRATION",
    "RECURRENCE", "REST", "CRISIS", "HERITAGE",
)

SIGNAL_WEIGHTS = {
    "crystal_confidence": 0.30,
    "first_time_pattern_break": 0.25,
    "ec_slope": 0.20,
    "mask_state": 0.10,
    "session_recency": 0.10,
    "heritage_correlation": 0.05,
}

_BREAKTHROUGH_COOLDOWN_HOURS = 48


class TherapeuticMomentClassifier:
    """Rule-based TMC using UCD spec Section 7.2 signal weights."""

    def __init__(self, db_pool):
        self.db_pool = db_pool

    async def classify(self, user_id: str) -> dict[str, Any]:
        """Classify the current therapeutic moment for a user.

        Returns dict with moment_class, confidence, signals, and safety_gate info.
        """
        signals = await self._gather_signals(user_id)

        safety = await self._check_safety_gates(user_id, signals)
        if safety.get("blocked"):
            return {
                "moment_class": safety.get("fallback_class", "REST"),
                "confidence": 0.5,
                "signals": signals,
                "safety_gate": safety,
                "classifier_version": "rule_v1",
            }

        scores = self._score_moment_classes(signals)

        best_class = max(scores, key=scores.get)
        best_score = scores[best_class]

        return {
            "moment_class": best_class,
            "confidence": round(best_score, 4),
            "signals": signals,
            "scores": {k: round(v, 4) for k, v in scores.items()},
            "safety_gate": safety,
            "classifier_version": "rule_v1",
        }

    async def _gather_signals(self, user_id: str) -> dict[str, Any]:
        """Aggregate signal values from all available sources."""
        signals: dict[str, Any] = {
            "crystal_confidence": 0.0,
            "crystal_domain": None,
            "first_time_pattern_break": False,
            "ec_slope": 0.0,
            "ec_current": 0.0,
            "mask_state": "UNMASKED",
            "session_recency_hours": 999.0,
            "heritage_correlation": 0.0,
            "deployment_context": "private",
        }
        if not self.db_pool:
            return signals

        try:
            async with self.db_pool.acquire() as conn:
                crystal = await conn.fetchrow(
                    "SELECT confidence, domain FROM nate_intelligence_crystals "
                    "WHERE (user_id IS NOT NULL AND user_id::text = $1) "
                    "AND superseded_by IS NULL AND scope != 'archived' "
                    "ORDER BY created_at DESC LIMIT 1",
                    user_id,
                )
                if crystal:
                    signals["crystal_confidence"] = float(crystal["confidence"] or 0)
                    signals["crystal_domain"] = crystal["domain"]

                cycle = await conn.fetchrow(
                    "SELECT is_first_break, detected_at FROM cycle_detections "
                    "WHERE user_id = $1 ORDER BY detected_at DESC LIMIT 1",
                    user_id,
                )
                if cycle:
                    signals["first_time_pattern_break"] = bool(cycle.get("is_first_break", False))

                ec_rows = await conn.fetch(
                    "SELECT c_emo, recorded_at FROM nevedal_coherence_log "
                    "WHERE user_id = $1 ORDER BY recorded_at DESC LIMIT 5",
                    user_id,
                )
                if ec_rows:
                    signals["ec_current"] = float(ec_rows[0]["c_emo"] or 0)
                    if len(ec_rows) >= 2:
                        recent = float(ec_rows[0]["c_emo"] or 0)
                        older = float(ec_rows[-1]["c_emo"] or 0)
                        signals["ec_slope"] = recent - older

                forge = await conn.fetchrow(
                    "SELECT mask_detection_state, deployment_context "
                    "FROM sse_identity_forge WHERE user_id = $1",
                    user_id,
                )
                if forge:
                    signals["mask_state"] = forge.get("mask_detection_state") or "UNMASKED"
                    signals["deployment_context"] = forge.get("deployment_context") or "private"

                last_session = await conn.fetchval(
                    "SELECT MAX(created_at) FROM conversation_history "
                    "WHERE user_id = $1",
                    user_id,
                )
                if last_session:
                    delta = datetime.now(timezone.utc) - last_session.replace(tzinfo=timezone.utc)
                    signals["session_recency_hours"] = delta.total_seconds() / 3600.0

                heritage = await conn.fetchval(
                    "SELECT MAX(correlation_strength) FROM heritage_correlation_index "
                    "WHERE crystal_user_id::text = $1",
                    user_id,
                )
                if heritage:
                    signals["heritage_correlation"] = float(heritage)

        except Exception as e:
            logger.warning("TMC signal gathering failed for %s: %s", user_id, e)

        return signals

    def _score_moment_classes(self, signals: dict) -> dict[str, float]:
        """Apply rule-based scoring using Section 7.2 weights."""
        crystal_conf = signals.get("crystal_confidence", 0.0)
        first_break = signals.get("first_time_pattern_break", False)
        ec_slope = signals.get("ec_slope", 0.0)
        mask_state = signals.get("mask_state", "UNMASKED")
        recency_hours = signals.get("session_recency_hours", 999.0)
        heritage = signals.get("heritage_correlation", 0.0)

        mask_factor = 1.0 if mask_state == "EVOLVING" else (0.3 if mask_state == "MASKED" else 0.6)
        recency_factor = max(0.0, 1.0 - (recency_hours / 168.0))

        weighted_sum = (
            crystal_conf * SIGNAL_WEIGHTS["crystal_confidence"]
            + (1.0 if first_break else 0.0) * SIGNAL_WEIGHTS["first_time_pattern_break"]
            + min(1.0, max(-1.0, ec_slope)) * SIGNAL_WEIGHTS["ec_slope"]
            + mask_factor * SIGNAL_WEIGHTS["mask_state"]
            + recency_factor * SIGNAL_WEIGHTS["session_recency"]
            + heritage * SIGNAL_WEIGHTS["heritage_correlation"]
        )

        scores = {}

        if crystal_conf >= 0.75 and first_break:
            scores["BREAKTHROUGH"] = weighted_sum * 1.3
        elif crystal_conf >= 0.75:
            scores["BREAKTHROUGH"] = weighted_sum * 0.8

        scores["THRESHOLD"] = weighted_sum * 0.9 if crystal_conf >= 0.5 else weighted_sum * 0.4

        scores["INTEGRATION"] = (
            weighted_sum * 1.1
            if ec_slope > 0.1 and not first_break
            else weighted_sum * 0.5
        )

        scores["RECURRENCE"] = (
            weighted_sum * 1.2
            if crystal_conf >= 0.5 and not first_break and ec_slope < -0.05
            else weighted_sum * 0.3
        )

        scores["CRISIS"] = weighted_sum * 1.5 if ec_slope < -0.3 else weighted_sum * 0.2

        scores["HERITAGE"] = heritage * 2.0 if heritage >= 0.3 else heritage * 0.5

        scores["REST"] = max(0.1, 1.0 - weighted_sum)

        for cls in MOMENT_CLASSES:
            if cls not in scores:
                scores[cls] = 0.0

        return scores

    async def _check_safety_gates(
        self, user_id: str, signals: dict
    ) -> dict[str, Any]:
        """MASKED-user BREAKTHROUGH gate + intensity cooldown + S3 predictive restraint."""
        result: dict[str, Any] = {"blocked": False}

        if signals.get("mask_state") == "MASKED":
            result["masked_user_gate"] = True

        if not self.db_pool:
            return result

        try:
            async with self.db_pool.acquire() as conn:
                last_breakthrough = await conn.fetchval(
                    "SELECT MAX(created_at) FROM intensity_ledger "
                    "WHERE user_id = $1 AND moment_class = 'BREAKTHROUGH'",
                    user_id,
                )
                if last_breakthrough:
                    since = datetime.now(timezone.utc) - last_breakthrough.replace(
                        tzinfo=timezone.utc
                    )
                    if since.total_seconds() < _BREAKTHROUGH_COOLDOWN_HOURS * 3600:
                        result["breakthrough_cooldown_active"] = True
                        result["hours_remaining"] = round(
                            _BREAKTHROUGH_COOLDOWN_HOURS
                            - since.total_seconds() / 3600,
                            1,
                        )
        except Exception as e:
            logger.warning("TMC safety gate check failed: %s", e)

        try:
            from .predictive_restraint import evaluate_safety
            deploy_ctx = signals.get("deployment_context", "private")
            s3_gate = await evaluate_safety(user_id, self.db_pool, deploy_ctx)
            result["predictive_restraint"] = s3_gate
            if s3_gate.get("blocked"):
                result["blocked"] = True
                result["fallback_class"] = "REST"
            if s3_gate.get("modality_restrictions"):
                result["modality_restrictions"] = s3_gate["modality_restrictions"]
        except Exception as e:
            logger.warning("S3 predictive restraint failed: %s", e)

        if result.get("masked_user_gate") or result.get("breakthrough_cooldown_active"):
            result["blocked"] = True
            result["fallback_class"] = "REST" if result.get("masked_user_gate") else "THRESHOLD"

        if not result.get("blocked") and signals.get("heritage_correlation", 0) >= 0.3:
            try:
                async with self.db_pool.acquire() as conn:
                    approved = await conn.fetchval(
                        "SELECT COUNT(*) FROM intensity_ledger "
                        "WHERE user_id = $1 AND moment_class = 'HERITAGE' "
                        "AND clinician_override = true AND created_at >= $2",
                        user_id,
                        datetime.now(timezone.utc) - timedelta(hours=168),
                    )
                    if not approved:
                        result["heritage_requires_clinician"] = True
                        result["blocked"] = True
                        result["fallback_class"] = "INTEGRATION"
            except Exception as e:
                logger.warning("Heritage clinician check failed: %s", e)

        return result

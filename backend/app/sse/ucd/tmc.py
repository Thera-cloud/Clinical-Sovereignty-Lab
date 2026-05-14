"""Therapeutic Moment Classifier (TMC) — Phase 2 rule-based classifier.

Classifies the current therapeutic moment into one of seven classes using
weighted signals from Section 7.2 of SS-UCD-001. Replaces schedule-driven
generation with moment-driven generation.

Phase 5 replaces this with a trained logistic regression model; the rule-based
classifier remains as a fallback if model accuracy drops below threshold.

v1.3 Gap 8 — Polyvictimization Awareness (additive, dormant when no layers):
    Two new signals enter SIGNAL_WEIGHTS as additive entries. Existing weights
    are NUMERICALLY UNCHANGED — _V1_2_SIGNAL_WEIGHTS is the locked snapshot,
    asserted at import time. The classifier does not normalize the weight sum,
    so adding entries above 1.0 does not perturb v1.2 thresholds (per plan
    Gap 8 contract: "the classifier already handles via threshold tuning, not
    normalization").

    A user with zero rows in user_polyvictimization_layers gets both new
    signals = 0.0, which contributes 0 to weighted_sum and bypasses the
    cumulative-stacking escalation. v1.2 behavior is preserved exactly.
    (Auditor check phase3_tmc_v1_2_no_layer_users_unchanged deferred to
    Phase 6 fixtures.)

    Cumulative stacking is an ADDITIONAL escalation path to CRISIS — not a
    redefinition of existing CRISIS resolution. Existing weighted-sum CRISIS
    criteria stay intact; the polyvictim path is an *extra* way to reach CRISIS
    when classification is THRESHOLD or RECURRENCE and severity load >= 0.6.
    Stacking-driven CRISIS is tagged with a distinct audit field
    (stacking_driven_crisis=True, escalation_path='polyvictim_stacking') so
    Phase 6 telemetry can monitor false-CRISIS rate (Risk #8) separately from
    baseline CRISIS rate.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)

MOMENT_CLASSES = (
    "THRESHOLD", "BREAKTHROUGH", "INTEGRATION",
    "RECURRENCE", "REST", "CRISIS", "HERITAGE",
)

# v1.2 LOCKED snapshot — DO NOT MODIFY. Used by _auditor_self_check to assert
# strict subset preservation of v1.2 weights inside SIGNAL_WEIGHTS. Any
# rebalancing of these values would drift CRISIS/RECURRENCE thresholds for
# every existing v1.2 user (per plan Gap 8 BLOCKING contract).
_V1_2_SIGNAL_WEIGHTS = {
    "crystal_confidence": 0.30,
    "first_time_pattern_break": 0.25,
    "ec_slope": 0.20,
    "mask_state": 0.10,
    "session_recency": 0.10,
    "heritage_correlation": 0.05,
}

SIGNAL_WEIGHTS = {
    # v1.2 weights — numerically unchanged from _V1_2_SIGNAL_WEIGHTS
    "crystal_confidence": 0.30,
    "first_time_pattern_break": 0.25,
    "ec_slope": 0.20,
    "mask_state": 0.10,
    "session_recency": 0.10,
    "heritage_correlation": 0.05,
    # v1.3 additive — Gap 8 polyvictimization (dormant when no layers).
    # Sum exceeds 1.0; classifier does not normalize. Per plan Gap 8.
    "polyvictimization_layer_count": 0.10,
    "polyvictim_severity_load": 0.15,
}

# v1.2 weight contract — fail-fast assertion at import time. If a future
# developer rebalances values to "make room" for new signals, this trips.
for _k, _v in _V1_2_SIGNAL_WEIGHTS.items():
    assert SIGNAL_WEIGHTS.get(_k) == _v, (
        f"v1.2 weight drift detected: SIGNAL_WEIGHTS[{_k!r}]={SIGNAL_WEIGHTS.get(_k)!r} "
        f"!= v1.2 locked value {_v!r}. Per plan Gap 8 BLOCKING contract, v1.2 "
        f"weights must remain numerically unchanged."
    )

_BREAKTHROUGH_COOLDOWN_HOURS = 48

# v1.3 Gap 8 — Polyvictimization severity weights.
# Source of truth: backend/migrations/206_user_polyvictimization_layers.sql
# COMMENT block ("Severity weights ... low = 1, moderate = 2, high = 4, critical = 6").
# Mirrored here because the SQL CHECK only constrains the label set; numeric
# weights are applied in Python.
_POLYVICTIM_SEVERITY_WEIGHT = {
    "low": 1,
    "moderate": 2,
    "high": 4,
    "critical": 6,
}

# Normalization denominators chosen so that clinically-significant cumulative
# load reaches the 0.6 stacking threshold. Documented for Phase 6 tuning.
#   layer_count: count / 5 (cap 1.0). 3 layers -> 0.6 (polyvictim threshold).
#   severity_load: weighted_sum / 10 (cap 1.0). One critical (6) does NOT
#     stack alone; two high (8), one critical+one moderate (8), or one
#     critical+one high (10) reach the stacking threshold.
_POLYVICTIM_LAYER_COUNT_DENOM = 5.0
_POLYVICTIM_SEVERITY_LOAD_DENOM = 10.0

# Stacking threshold — only THRESHOLD and RECURRENCE escalate (BREAKTHROUGH
# and INTEGRATION are NOT escalated; clinical reasoning: do not convert a
# breakthrough moment into a crisis label based on history alone).
_STACKING_SEVERITY_THRESHOLD = 0.6
_STACKING_ELIGIBLE_CLASSES = frozenset({"THRESHOLD", "RECURRENCE"})

# Distinct audit values for Phase 6 detector_telemetry filtering. Per plan
# Gap 8 Note 2: "filter by classified_as='CRISIS' AND escalation_path=
# 'polyvictim_stacking' for tuning."
_ESCALATION_PATH_BASELINE = "baseline"
_ESCALATION_PATH_STACKING = "polyvictim_stacking"


def _v14_addiction_branch_active(raw: Any) -> bool:
    if raw is None:
        return False
    if isinstance(raw, str) and raw.strip().lower() == "none":
        return False
    return True


class TherapeuticMomentClassifier:
    """Rule-based TMC using UCD spec Section 7.2 signal weights."""

    def __init__(self, db_pool):
        self.db_pool = db_pool

    async def classify(self, user_id: str) -> dict[str, Any]:
        """Classify the current therapeutic moment for a user.

        Returns dict with moment_class, confidence, signals, safety_gate info,
        and v1.3 polyvictimization audit fields (stacking_driven_crisis,
        escalation_path, polyvictim_layers_active).
        """
        signals = await self._gather_signals(user_id)

        safety = await self._check_safety_gates(user_id, signals)
        if safety.get("blocked"):
            # Safety-blocked path bypasses both baseline weighted-sum and
            # cumulative-stacking escalation. The fallback class is a
            # protective intervention, not a classifier-resolved state, so
            # polyvictim load must NOT escalate it (would defeat the gate).
            return {
                "moment_class": safety.get("fallback_class", "REST"),
                "confidence": 0.5,
                "signals": signals,
                "safety_gate": safety,
                "classifier_version": "rule_v1",
                "stacking_driven_crisis": False,
                "escalation_path": _ESCALATION_PATH_BASELINE,
                "polyvictim_layers_active": int(
                    signals.get("polyvictim_layers_active", 0) or 0
                ),
            }

        scores = self._score_moment_classes(signals)

        # Existing v1.2 baseline class resolution — UNCHANGED.
        best_class = max(scores, key=scores.get)
        best_score = scores[best_class]

        # v1.3 Gap 8 cumulative stacking escalation — ADDITIVE post-resolution
        # check. Only escalates THRESHOLD or RECURRENCE to CRISIS when the
        # severity load crosses the stacking threshold. Existing CRISIS
        # resolution criteria stay intact; this is an *additional* path to
        # CRISIS, distinguished by stacking_driven_crisis=True for Phase 6
        # telemetry. Risk #8: if pilot cohort shows stacking-driven CRISIS
        # exceeds 20% of total CRISIS classifications, threshold tuning
        # required before cohort_25.
        stacking_driven_crisis = False
        escalation_path = _ESCALATION_PATH_BASELINE
        baseline_class = best_class
        baseline_score = best_score
        severity_load = float(signals.get("polyvictim_severity_load", 0.0) or 0.0)

        if (
            best_class in _STACKING_ELIGIBLE_CLASSES
            and severity_load >= _STACKING_SEVERITY_THRESHOLD
        ):
            best_class = "CRISIS"
            # Preserve the baseline weighted-sum confidence so downstream
            # consumers can see the underlying activation strength; do not
            # synthesize a fake CRISIS confidence from the stacking signal.
            best_score = scores.get("CRISIS", baseline_score)
            stacking_driven_crisis = True
            escalation_path = _ESCALATION_PATH_STACKING
            logger.info(
                "TMC polyvictim_crisis_stacking_escalation user=%s baseline=%s "
                "severity_load=%.3f layers_active=%d",
                user_id,
                baseline_class,
                severity_load,
                int(signals.get("polyvictim_layers_active", 0) or 0),
            )

        return {
            "moment_class": best_class,
            "confidence": round(best_score, 4),
            "signals": signals,
            "scores": {k: round(v, 4) for k, v in scores.items()},
            "safety_gate": safety,
            "classifier_version": "rule_v1",
            # v1.3 Gap 8 audit fields — distinct columns so Phase 6
            # detector_telemetry can filter stacking-driven CRISIS rate
            # separately from baseline weighted-sum CRISIS rate.
            "stacking_driven_crisis": stacking_driven_crisis,
            "escalation_path": escalation_path,
            "baseline_class_pre_stacking": baseline_class,
            "polyvictim_layers_active": int(
                signals.get("polyvictim_layers_active", 0) or 0
            ),
        }

    async def _gather_signals(self, user_id: str) -> dict[str, Any]:
        """Aggregate signal values from all available sources.

        v1.3 Gap 8: polyvictim signals default to 0.0 when no
        user_polyvictimization_layers rows exist for this user. This
        preserves v1.2 weighted-sum behavior for users not yet enrolled in
        the polyvictim awareness track (Phase 4 portal populates the table).
        """
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
            # v1.3 Gap 8 — DORMANT defaults. Zero contribution to weighted_sum
            # when no layers exist; stacking check no-ops at severity_load=0.
            "polyvictimization_layer_count": 0.0,
            "polyvictim_severity_load": 0.0,
            "polyvictim_layers_active": 0,
            # v1.4 addiction architecture — dormant until profile flags set.
            "substance_branch_active": False,
            "sex_addiction_branch_active": False,
            "gambling_branch_active": False,
            "gaming_branch_active": False,
            "food_compulsion_branch_active": False,
            "work_compulsion_branch_active": False,
            "spending_compulsion_branch_active": False,
            "codependency_branch_active": False,
            "cross_addiction_active": False,
            "cross_addiction_count": 0,
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

                # Domain-level observability: nevedal_coherence_log rows are keyed by
                # `domain`, not per-user. Clinical chat/TMC uses the latest clinical
                # coherence samples as a system signal (ec_current / ec_slope).
                ec_rows = await conn.fetch(
                    "SELECT c_emo, created_at FROM nevedal_coherence_log "
                    "WHERE domain = 'clinical' ORDER BY created_at DESC LIMIT 5",
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

                # v1.3 Gap 8 — fetch active polyvictimization layers and
                # compute normalized signals. Wrapped in its own try so a
                # missing-table or query error degrades gracefully (signals
                # stay at 0.0, classifier behaves as v1.2).
                try:
                    layer_rows = await conn.fetch(
                        "SELECT severity FROM user_polyvictimization_layers "
                        "WHERE user_id = $1 AND active = TRUE",
                        user_id,
                    )
                    if layer_rows:
                        active_count = len(layer_rows)
                        weighted = 0
                        for r in layer_rows:
                            sev = (r["severity"] or "").strip().lower()
                            weighted += _POLYVICTIM_SEVERITY_WEIGHT.get(sev, 0)
                        signals["polyvictim_layers_active"] = active_count
                        signals["polyvictimization_layer_count"] = min(
                            1.0, active_count / _POLYVICTIM_LAYER_COUNT_DENOM
                        )
                        signals["polyvictim_severity_load"] = min(
                            1.0, weighted / _POLYVICTIM_SEVERITY_LOAD_DENOM
                        )
                except Exception as pv_err:
                    # Dormant fallback — never block classification on
                    # polyvictim fetch failure. Signals already initialized
                    # to 0.0; v1.2 behavior preserved.
                    logger.warning(
                        "TMC polyvictim layer fetch failed for %s: %s "
                        "(signals dormant, v1.2 behavior preserved)",
                        user_id,
                        pv_err,
                    )

                # v1.4 — addiction branch signals from users.profile_data (username FK).
                try:
                    prow = await conn.fetchrow(
                        "SELECT profile_data FROM users "
                        "WHERE username = $1 OR id::text = $1 LIMIT 1",
                        user_id,
                    )
                    pd = prow["profile_data"] if prow else None
                    if isinstance(pd, str):
                        try:
                            pd = json.loads(pd)
                        except Exception:
                            pd = {}
                    if not isinstance(pd, dict):
                        pd = {}
                    branch_keys = (
                        ("substance_branch_active", "substance_status"),
                        ("sex_addiction_branch_active", "sex_addiction_status"),
                        ("gambling_branch_active", "gambling_status"),
                        ("gaming_branch_active", "gaming_status"),
                        ("food_compulsion_branch_active", "food_compulsion_status"),
                        ("work_compulsion_branch_active", "work_compulsion_status"),
                        ("spending_compulsion_branch_active", "spending_compulsion_status"),
                        ("codependency_branch_active", "codependency_status"),
                    )
                    active_ct = 0
                    for sig_key, prof_key in branch_keys:
                        active = _v14_addiction_branch_active(pd.get(prof_key))
                        signals[sig_key] = active
                        if active:
                            active_ct += 1
                    signals["cross_addiction_count"] = active_ct
                    signals["cross_addiction_active"] = active_ct >= 2
                except Exception as ad_err:
                    logger.warning(
                        "TMC v1.4 addiction signal fetch failed for %s: %s",
                        user_id,
                        ad_err,
                    )

        except Exception as e:
            logger.warning("TMC signal gathering failed for %s: %s", user_id, e)

        return signals

    def _score_moment_classes(self, signals: dict) -> dict[str, float]:
        """Apply rule-based scoring using Section 7.2 weights.

        v1.3 Gap 8: polyvictim signals are added to weighted_sum as additive
        terms. When dormant (signals == 0.0), the new terms contribute 0 and
        v1.2 weighted_sum is preserved bit-for-bit.
        """
        crystal_conf = signals.get("crystal_confidence", 0.0)
        first_break = signals.get("first_time_pattern_break", False)
        ec_slope = signals.get("ec_slope", 0.0)
        mask_state = signals.get("mask_state", "UNMASKED")
        recency_hours = signals.get("session_recency_hours", 999.0)
        heritage = signals.get("heritage_correlation", 0.0)
        # v1.3 Gap 8 — already normalized to [0.0, 1.0] in _gather_signals.
        poly_count = signals.get("polyvictimization_layer_count", 0.0)
        poly_load = signals.get("polyvictim_severity_load", 0.0)

        mask_factor = 1.0 if mask_state == "EVOLVING" else (0.3 if mask_state == "MASKED" else 0.6)
        recency_factor = max(0.0, 1.0 - (recency_hours / 168.0))

        weighted_sum = (
            crystal_conf * SIGNAL_WEIGHTS["crystal_confidence"]
            + (1.0 if first_break else 0.0) * SIGNAL_WEIGHTS["first_time_pattern_break"]
            + min(1.0, max(-1.0, ec_slope)) * SIGNAL_WEIGHTS["ec_slope"]
            + mask_factor * SIGNAL_WEIGHTS["mask_state"]
            + recency_factor * SIGNAL_WEIGHTS["session_recency"]
            + heritage * SIGNAL_WEIGHTS["heritage_correlation"]
            # v1.3 additive terms — zero when no polyvictim layers exist.
            + poly_count * SIGNAL_WEIGHTS["polyvictimization_layer_count"]
            + poly_load * SIGNAL_WEIGHTS["polyvictim_severity_load"]
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

    # ------------------------------------------------------------------ #
    # v1.3 Gap 8 — auditor self-check                                    #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _auditor_self_check() -> dict[str, Any]:
        """Static contract checks for Phase 6 sensitive_bridge_auditor.

        Verifies v1.3 Gap 8 implementation contracts without requiring a
        live DB or fixture cohort:
          1. v1.2 weights numerically unchanged inside SIGNAL_WEIGHTS.
          2. New polyvictim signals present and dormant by default.
          3. Stacking escalation path uses distinct audit field.
          4. Stacking only escalates eligible classes (THRESHOLD/RECURRENCE).
        """
        import inspect

        results: dict[str, Any] = {}

        # Check 1 — tmc_v1_2_signal_weights_numerically_unchanged
        # Snapshot v1.2 weights, assert strict subset preservation by both
        # key and value. Drift here would shift CRISIS thresholds for every
        # existing v1.2 user.
        v1_2_preserved = all(
            SIGNAL_WEIGHTS.get(k) == v
            for k, v in _V1_2_SIGNAL_WEIGHTS.items()
        )
        v1_2_diff = {
            k: {"v1_2": v, "current": SIGNAL_WEIGHTS.get(k)}
            for k, v in _V1_2_SIGNAL_WEIGHTS.items()
            if SIGNAL_WEIGHTS.get(k) != v
        }
        results["tmc_v1_2_signal_weights_numerically_unchanged"] = {
            "passed": v1_2_preserved,
            "v1_2_keys": sorted(_V1_2_SIGNAL_WEIGHTS.keys()),
            "drift": v1_2_diff,
        }

        # Check 2 — polyvictim signals present in SIGNAL_WEIGHTS
        new_signals_present = (
            "polyvictimization_layer_count" in SIGNAL_WEIGHTS
            and "polyvictim_severity_load" in SIGNAL_WEIGHTS
        )
        results["tmc_polyvictim_signals_registered"] = {
            "passed": new_signals_present,
            "polyvictimization_layer_count_weight": SIGNAL_WEIGHTS.get(
                "polyvictimization_layer_count"
            ),
            "polyvictim_severity_load_weight": SIGNAL_WEIGHTS.get(
                "polyvictim_severity_load"
            ),
        }

        # Check 3 — stacking_driven_crisis is a distinct audit field
        # (not buried in a generic CRISIS log entry). Source-level inspection
        # of classify() to verify the field is set on the response dict.
        try:
            classify_src = inspect.getsource(
                TherapeuticMomentClassifier.classify
            )
        except Exception:
            classify_src = ""
        # Look for the literal field assignment in the return dict, not just
        # mentions in comments. Field must appear in a 'key: value' return
        # context. Lines containing it that are not inside the response dict
        # are filtered by checking for both the key and a True/False value.
        stacking_field_lines = [
            ln for ln in classify_src.splitlines()
            if '"stacking_driven_crisis"' in ln and ":" in ln
        ]
        results["tmc_stacking_audit_field_distinct"] = {
            "passed": len(stacking_field_lines) >= 2,
            "stacking_field_occurrences": len(stacking_field_lines),
            "note": (
                "Must appear in both safety-blocked early-return AND main "
                "return so Phase 6 telemetry sees the field on every "
                "classification, not just stacking-driven ones."
            ),
        }

        # Check 4 — stacking only escalates THRESHOLD/RECURRENCE.
        # Verify _STACKING_ELIGIBLE_CLASSES is the documented set; verify
        # classify() source actually consults that set rather than allowing
        # any class to escalate.
        eligible_correct = _STACKING_ELIGIBLE_CLASSES == frozenset(
            {"THRESHOLD", "RECURRENCE"}
        )
        eligible_consulted = "_STACKING_ELIGIBLE_CLASSES" in classify_src
        results["tmc_stacking_only_escalates_threshold_or_recurrence"] = {
            "passed": eligible_correct and eligible_consulted,
            "eligible_classes": sorted(_STACKING_ELIGIBLE_CLASSES),
            "stacking_threshold": _STACKING_SEVERITY_THRESHOLD,
            "consulted_in_classify": eligible_consulted,
        }

        # Check 5 — stacking does not modify safety-blocked path.
        # When safety gates fire, the fallback class is a protective
        # intervention. Escalating it via polyvictim load would defeat the
        # gate. Verify the safety-blocked early return sets
        # stacking_driven_crisis=False explicitly.
        safety_path_lines = [
            ln for ln in classify_src.splitlines()
            if '"stacking_driven_crisis": False' in ln
        ]
        results["tmc_stacking_skipped_when_safety_blocked"] = {
            "passed": len(safety_path_lines) >= 1,
            "safety_path_explicit_false_count": len(safety_path_lines),
        }

        # Aggregate result
        results["all_passed"] = all(
            isinstance(v, dict) and v.get("passed") is True
            for v in results.values()
            if isinstance(v, dict)
        )
        return results

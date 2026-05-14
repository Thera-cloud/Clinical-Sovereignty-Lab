"""Tests for BridgeDecision transcript leak validator (Note 3a, v1.4 R1)."""

import pytest

from app.services.sensitive_clinical_bridge import (
    BridgeDecision,
    BridgeDecisionRedactionError,
    BRIDGE_DECISION_SCHEMA_HASH,
    BRIDGE_DECISION_SCHEMA_VERSION,
    CoercionSummary,
    DissociationSummary,
    EmbodimentPhaseApplied,
    IntrojectionSummary,
    LegalProximity,
    NoveltyGateState,
    PolyvictimLoad,
    ReengagementSummary,
    SubstanceRegisterBranch,
    TriggerDateMatch,
    _AUDIT_FIELD_SOURCES_KEY,
    _SOURCE_KIND_FRAMEWORK_DIRECTIVE,
    _validate_no_raw_transcript_leak,
)


def _base_decision(audit_event: dict) -> BridgeDecision:
    return BridgeDecision(
        register_directive=None,
        coach_alert=None,
        resource_block=None,
        scope_statement=None,
        audit_event=audit_event,
        novelty_gate_state=NoveltyGateState(
            blocked=False,
            reason="signals_below_threshold",
            dissociation_delta=0.0,
            coercion_severity=0.0,
            threshold=0.30,
            forced_on=False,
        ),
        arousal_load=None,
        introjection_signal=IntrojectionSummary(
            detected=False, score=0.0, drift_markers=()
        ),
        reengagement_signal=ReengagementSummary(
            detected=False, severity="none", matched_labels=()
        ),
        polyvictim_load=PolyvictimLoad(
            layers_active=0, severity_load=0.0, stacking_eligible=False
        ),
        embodiment_phase_applied=EmbodimentPhaseApplied(
            phase=None, set_at=None, set_by_clinician_id=None
        ),
        trigger_date_match=TriggerDateMatch(
            matched=False, date_type=None, severity=None, match_count=0
        ),
        legal_proximity=LegalProximity(
            detected=False,
            case_type=None,
            case_status=None,
            days_until_next_event=None,
        ),
        substance_register_branch=SubstanceRegisterBranch(
            branched=False, reason="not_active"
        ),
        prebuffer_required=False,
        prebuffer_text=None,
        coercion_test=CoercionSummary(
            detected=False, severity=0.0, matched_labels=()
        ),
        dissociation_signal=DissociationSummary(
            delta=0.0, length_anomaly_z=0.0, markers=()
        ),
        trafficking_classification=None,
        tmc_class="REST",
        selected_register_source="default",
        schema_version=BRIDGE_DECISION_SCHEMA_VERSION,
        schema_hash=BRIDGE_DECISION_SCHEMA_HASH,
        decided_at="1970-01-01T00:00:00+00:00",
    )


_OVERLAP_PHRASE = "internal parts today"


def test_lens_directives_block_exempt_when_framework_directive_tagged():
    user_msg = f"We discussed {_OVERLAP_PHRASE} in session."
    lens_text = (
        f"IFS-informed framing: clinicians often explore {_OVERLAP_PHRASE} "
        "with explicit consent and pacing."
    )
    decision = _base_decision(
        {
            "event_type": "disclosure_evaluated",
            "lens_directives_block": lens_text,
            _AUDIT_FIELD_SOURCES_KEY: {
                "lens_directives_block": _SOURCE_KIND_FRAMEWORK_DIRECTIVE,
            },
        }
    )
    _validate_no_raw_transcript_leak(decision, user_msg)


def test_lens_directives_block_raises_when_overlap_without_tag():
    user_msg = f"We discussed {_OVERLAP_PHRASE} in session."
    lens_text = (
        f"IFS-informed framing: clinicians often explore {_OVERLAP_PHRASE} "
        "with explicit consent and pacing."
    )
    decision = _base_decision(
        {
            "event_type": "disclosure_evaluated",
            "lens_directives_block": lens_text,
        }
    )
    with pytest.raises(BridgeDecisionRedactionError) as excinfo:
        _validate_no_raw_transcript_leak(decision, user_msg)
    assert "lens_directives_block" in str(excinfo.value.field_path)


def test_lens_directives_block_raises_when_wrong_source_kind():
    user_msg = f"We discussed {_OVERLAP_PHRASE} in session."
    lens_text = (
        f"IFS-informed framing: clinicians often explore {_OVERLAP_PHRASE} "
        "with explicit consent and pacing."
    )
    decision = _base_decision(
        {
            "event_type": "disclosure_evaluated",
            "lens_directives_block": lens_text,
            _AUDIT_FIELD_SOURCES_KEY: {
                "lens_directives_block": "verbatim_transcript_snippet",
            },
        }
    )
    with pytest.raises(BridgeDecisionRedactionError):
        _validate_no_raw_transcript_leak(decision, user_msg)

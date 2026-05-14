"""Tests for enrollment full activation and client-initiated Sensitive Profile."""

import json

import pytest


def test_full_activation_gap_features_count_matches_canonical_lists():
    from app.services.sensitive_clinical_bridge import (
        FULL_ACTIVATION_GAP_FEATURES,
        _FEATURE_FLAG_NAMES,
        _V1_4_FEATURE_FLAG_NAMES,
    )

    assert len(_FEATURE_FLAG_NAMES) == 16
    assert len(_V1_4_FEATURE_FLAG_NAMES) == 7
    assert len(FULL_ACTIVATION_GAP_FEATURES) == 23
    for name in _FEATURE_FLAG_NAMES:
        assert FULL_ACTIVATION_GAP_FEATURES.get(name) is True
    for name in _V1_4_FEATURE_FLAG_NAMES:
        assert FULL_ACTIVATION_GAP_FEATURES.get(name) is True


def test_migration_220_json_matches_python_ssot():
    from app.services.sensitive_clinical_bridge import FULL_ACTIVATION_GAP_FEATURES

    migration_blob = """
{"gap_introjection_enabled": true, "gap_thalamic_gate_enabled": true, "gap_reengagement_enabled": true, "gap_arousal_cap_enabled": true, "gap_polyvictim_load_enabled": true, "gap_dual_diagnosis_enabled": true, "gap_active_disclosure_enabled": true, "gap_codeword_enabled": true, "gap_trigger_dates_enabled": true, "gap_legal_status_enabled": true, "gap_embodiment_phase_enabled": true, "gap_jurisdiction_compliance_enabled": true, "gap_minor_survivor_protections_enabled": true, "gap_parenting_no_pathologization_enabled": true, "gap_rj_companioning_enabled": true, "gap_cultural_context_enabled": true, "v1_4_codeword_listener_enabled": true, "v1_4_addiction_branches_enabled": true, "v1_4_cross_addiction_overlay_enabled": true, "v1_4_dst_lens_enabled": true, "v1_4_framework_lens_enabled": true, "v1_4_crystal_factory_enabled": true, "v1_4_alert_dispatch_enabled": true}
"""
    mig = json.loads(migration_blob)
    assert mig == FULL_ACTIVATION_GAP_FEATURES


def test_any_sensitive_feature_active_with_full_enrollment_flags():
    from app.services.sensitive_clinical_bridge import (
        FULL_ACTIVATION_GAP_FEATURES,
        _any_sensitive_feature_active,
    )

    enrollment = {"raw_flags": dict(FULL_ACTIVATION_GAP_FEATURES)}
    effective = {k: bool(v) for k, v in FULL_ACTIVATION_GAP_FEATURES.items() if k.startswith("gap_")}
    assert _any_sensitive_feature_active(effective, enrollment) is True

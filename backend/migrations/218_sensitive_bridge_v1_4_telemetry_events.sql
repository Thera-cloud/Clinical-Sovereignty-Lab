-- ============================================================================
-- Migration 218: Sensitive Bridge v1.4 telemetry event contract
-- Additive only. Extends sensitive_bridge_log.event_type to include the
-- fourteen v1.4 telemetry events required by the addiction architecture plan.
-- ============================================================================

ALTER TABLE sensitive_bridge_log
  DROP CONSTRAINT IF EXISTS sensitive_bridge_log_event_type_check;

ALTER TABLE sensitive_bridge_log
  ADD CONSTRAINT sensitive_bridge_log_event_type_check
  CHECK (event_type IN (
    'disclosure_evaluated',
    'introjection_detected',
    'codeword_triggered',
    'codeword_triggered_with_mandatory_reporting_path',
    'arousal_cap_triggered',
    'thalamic_gate_blocked',
    'trigger_date_active',
    'embodiment_phase_filter_applied',
    'reengagement_pattern_detected',
    'polyvictim_load_applied',
    'legal_event_proximity_detected',
    'dual_diagnosis_register_applied',
    'safe_silence_mode_state_change',
    'safe_silence_mode_expiry_warning',
    'safe_silence_mode_auto_reverted',
    'sensitive_profile_mutation',
    'validator_lexicon_filter_applied',
    'validator_minor_protection_filter',
    'validator_parenting_pathologization_filter',
    'reporting_trigger_fired',
    'coach_handoff_emitted',
    'active_trafficking_disclosed',
    'imminent_danger_detected',
    'survivor_recruiter_role_disclosed',
    'jurisdiction_policy_applied',
    'survivor_data_export_requested',
    'minor_survivor_mandatory_reporting_auto_fired',
    'guardian_dual_approval_required',
    'parenting_crisis_alert_fired',
    'rj_companioning_register_applied',
    'cultural_context_register_applied',
    'locale_fallback_applied',
    'gap_feature_auto_disabled',
    'feature_flags_initialized',
    'auto_disable_armed',
    'auto_disable_committed',
    'auto_disable_cancelled',
    'auto_disable_reenabled',
    'data_export_requested',
    'data_export_downloaded',
    'data_export_expired',
    'crystal_seed_ingested',
    'crystal_seed_validator_block',
    'crystal_seed_embodiment_block',
    'sensitive_profile_screen_opened',
    'enrollment_created',
    'addiction_status_update',
    'addiction_branch_activated',
    'addiction_lexicon_match',
    'addiction_response_generated',
    'coach_alert_dispatched',
    'coach_alert_acknowledged',
    'referral_suggested',
    'referral_acknowledged',
    'crisis_warm_handoff',
    'cross_addiction_transfer_logged',
    'part_codeword_match',
    'framework_lens_selected',
    'trafficking_disclosure_detected',
    'pii_redaction_applied'
  ));

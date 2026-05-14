-- ============================================================================
-- Migration 220: Enrollment defaults to full v1.3+v1.4 gap activation JSONB;
-- client_initiated flags on codewords/parts; audit event types for backfill +
-- client-initiated saves. Sync gap JSON keys with
-- sensitive_clinical_bridge.FULL_ACTIVATION_GAP_FEATURES (Python SSOT).
-- ============================================================================

ALTER TABLE user_safety_codewords
  ADD COLUMN IF NOT EXISTS client_initiated BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE user_parts_registry
  ADD COLUMN IF NOT EXISTS client_initiated BOOLEAN NOT NULL DEFAULT FALSE;

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
    'pii_redaction_applied',
    'enrollment_backfilled_to_full_activation',
    'codeword_client_initiated',
    'part_client_initiated'
  ));

-- Full activation object (23 keys): must match FULL_ACTIVATION_GAP_FEATURES in Python.
WITH full_activation AS (
  SELECT $$
{"gap_introjection_enabled": true, "gap_thalamic_gate_enabled": true, "gap_reengagement_enabled": true, "gap_arousal_cap_enabled": true, "gap_polyvictim_load_enabled": true, "gap_dual_diagnosis_enabled": true, "gap_active_disclosure_enabled": true, "gap_codeword_enabled": true, "gap_trigger_dates_enabled": true, "gap_legal_status_enabled": true, "gap_embodiment_phase_enabled": true, "gap_jurisdiction_compliance_enabled": true, "gap_minor_survivor_protections_enabled": true, "gap_parenting_no_pathologization_enabled": true, "gap_rj_companioning_enabled": true, "gap_cultural_context_enabled": true, "v1_4_codeword_listener_enabled": true, "v1_4_addiction_branches_enabled": true, "v1_4_cross_addiction_overlay_enabled": true, "v1_4_dst_lens_enabled": true, "v1_4_framework_lens_enabled": true, "v1_4_crystal_factory_enabled": true, "v1_4_alert_dispatch_enabled": true}
$$::jsonb AS j
),
upd AS (
  UPDATE sensitive_bridge_enrollment e
     SET gap_features_enabled = (SELECT j FROM full_activation),
         last_modified_at = NOW(),
         last_modified_by = 'migration_220_enrollment_full_activation'
   WHERE gap_features_enabled IS NULL
      OR gap_features_enabled = '{}'::jsonb
  RETURNING e.user_id
)
INSERT INTO sensitive_bridge_log (
  user_id, event_type, event_severity,
  payload_json, decision_summary,
  occurred_at, recorded_by, access_classification,
  pii_screened_at, redaction_pass_count
)
SELECT
  user_id,
  'enrollment_backfilled_to_full_activation',
  'low',
  jsonb_build_object(
    'migration', '220',
    'mutation_kind', 'enrollment_backfilled_to_full_activation'
  ),
  jsonb_build_object('contract_version', '220_enrollment_full_activation'),
  NOW(),
  'migration_220_enrollment_full_activation',
  'clinician_and_admin',
  NOW(),
  1
FROM upd;

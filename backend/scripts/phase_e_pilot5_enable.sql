-- Phase E pilot_5 enablement — 5 named clients + master switch ON
-- Operator: DrNevedal1 / 2026-06-09
-- Pilot usernames: LetsGoLisa, magicguy72, lanasmith, hennons31, longra

BEGIN;

-- Full activation JSON (23 keys) — matches FULL_ACTIVATION_GAP_FEATURES / migration 220
CREATE TEMP TABLE _full_activation AS
SELECT $$
{"gap_introjection_enabled": true, "gap_thalamic_gate_enabled": true, "gap_reengagement_enabled": true, "gap_arousal_cap_enabled": true, "gap_polyvictim_load_enabled": true, "gap_dual_diagnosis_enabled": true, "gap_active_disclosure_enabled": true, "gap_codeword_enabled": true, "gap_trigger_dates_enabled": true, "gap_legal_status_enabled": true, "gap_embodiment_phase_enabled": true, "gap_jurisdiction_compliance_enabled": true, "gap_minor_survivor_protections_enabled": true, "gap_parenting_no_pathologization_enabled": true, "gap_rj_companioning_enabled": true, "gap_cultural_context_enabled": true, "v1_4_codeword_listener_enabled": true, "v1_4_addiction_branches_enabled": true, "v1_4_cross_addiction_overlay_enabled": true, "v1_4_dst_lens_enabled": true, "v1_4_framework_lens_enabled": true, "v1_4_crystal_factory_enabled": true, "v1_4_alert_dispatch_enabled": true}
$$::jsonb AS j;

-- Step 1: Blank non-pilot enrollments that still carry per-user gap flags
WITH blanked AS (
  UPDATE sensitive_bridge_enrollment e
     SET gap_features_enabled = '{}'::jsonb,
         last_modified_at = NOW(),
         last_modified_by = 'phase_e_pilot5_enable'
   WHERE cohort_label IS DISTINCT FROM 'pilot_5'
     AND gap_features_enabled IS NOT NULL
     AND gap_features_enabled <> '{}'::jsonb
  RETURNING e.user_id, e.cohort_label
)
INSERT INTO sensitive_bridge_log (
  user_id, event_type, event_severity, payload_json, decision_summary,
  occurred_at, recorded_by, access_classification, pii_screened_at, redaction_pass_count
)
SELECT
  user_id,
  'sensitive_profile_mutation',
  'low',
  jsonb_build_object(
    'mutation_kind', 'gap_features_blanked',
    'phase', 'E',
    'prior_cohort', cohort_label,
    'reason', 'non_pilot_phase_e_safety'
  ),
  jsonb_build_object('contract_version', 'phase_e_pilot5_enable'),
  NOW(),
  'phase_e_pilot5_enable',
  'clinician_and_admin',
  NOW(),
  1
FROM blanked;

-- Step 2: Upsert pilot_5 cohort + full activation for the 5 named clients
WITH pilot_users AS (
  SELECT unnest(ARRAY[
    'LetsGoLisa', 'magicguy72', 'lanasmith', 'hennons31', 'longra'
  ]::text[]) AS user_id
),
upserted AS (
  INSERT INTO sensitive_bridge_enrollment (
    user_id, cohort_label, gap_features_enabled, enrolled_by, notes,
    last_modified_at, last_modified_by
  )
  SELECT
    p.user_id,
    'pilot_5',
    (SELECT j FROM _full_activation),
    'DrNevedal1',
    'Phase E pilot_5 — Lisa West, Magicguy72, Lana Smith, Marcus Hennon, Ryan Long',
    NOW(),
    'phase_e_pilot5_enable'
  FROM pilot_users p
  WHERE EXISTS (SELECT 1 FROM users u WHERE u.username = p.user_id)
  ON CONFLICT (user_id) DO UPDATE SET
    cohort_label = 'pilot_5',
    gap_features_enabled = (SELECT j FROM _full_activation),
    last_modified_at = NOW(),
    last_modified_by = 'phase_e_pilot5_enable',
    notes = COALESCE(sensitive_bridge_enrollment.notes, '')
      || ' | phase_e_pilot5_enable 2026-06-09'
  RETURNING user_id, xmax = 0 AS inserted
)
INSERT INTO sensitive_bridge_log (
  user_id, event_type, event_severity, payload_json, decision_summary,
  occurred_at, recorded_by, access_classification, pii_screened_at, redaction_pass_count
)
SELECT
  user_id,
  CASE WHEN inserted THEN 'enrollment_created' ELSE 'enrollment_backfilled_to_full_activation' END,
  'moderate',
  jsonb_build_object(
    'phase', 'E',
    'cohort_label', 'pilot_5',
    'gap_features', 'full_activation',
    'enrolled_by', 'DrNevedal1'
  ),
  jsonb_build_object('contract_version', 'phase_e_pilot5_enable'),
  NOW(),
  'phase_e_pilot5_enable',
  'clinician_and_admin',
  NOW(),
  1
FROM upserted;

-- Step 3: Flip master kill switch ON (global orchestrator gate)
UPDATE app_settings
   SET setting_value = 'true'::jsonb,
       updated_at = NOW(),
       updated_by = 'DrNevedal1'
 WHERE setting_key = 'sensitive_bridge_master_enabled';

INSERT INTO sensitive_bridge_log (
  user_id, event_type, event_severity, payload_json, decision_summary,
  occurred_at, recorded_by, access_classification, pii_screened_at, redaction_pass_count
)
VALUES (
  'system',
  'feature_flags_initialized',
  'info',
  jsonb_build_object(
    'phase', 'E',
    'action', 'master_switch_enabled',
    'pilot_usernames', jsonb_build_array(
      'LetsGoLisa', 'magicguy72', 'lanasmith', 'hennons31', 'longra'
    ),
    'observation_window_hours', 24
  ),
  jsonb_build_object('contract_version', 'phase_e_pilot5_enable'),
  NOW(),
  'DrNevedal1',
  'admin_only_redacted',
  NOW(),
  1
);

COMMIT;

-- Verification (run after commit)
SELECT setting_key, setting_value, updated_by, updated_at
  FROM app_settings
 WHERE setting_key = 'sensitive_bridge_master_enabled';

SELECT e.user_id, e.cohort_label,
       (e.gap_features_enabled <> '{}'::jsonb) AS has_flags,
       (SELECT count(*)::int FROM jsonb_each(e.gap_features_enabled)) AS flag_count
  FROM sensitive_bridge_enrollment e
 WHERE e.user_id IN ('LetsGoLisa', 'magicguy72', 'lanasmith', 'hennons31', 'longra')
 ORDER BY e.user_id;

SELECT user_id, cohort_label, gap_features_enabled
  FROM sensitive_bridge_enrollment
 WHERE cohort_label = 'pilot_5'
 ORDER BY user_id;

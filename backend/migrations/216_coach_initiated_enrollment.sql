-- =============================================================================
-- Migration 216: Coach-Initiated Enrollment Schema Extensions
--
-- Extends two CHECK constraints to support the coach-initiated self-enrollment
-- surface added to SensitiveClinicalProfileScreen (Path C):
--
--   1. sensitive_bridge_enrollment.cohort_label CHECK extended to include
--      'inspection_test', 'pilot_5', 'general_availability'
--      ----------------------------------------------------------------
--      M209 originally seeded with the operational rollout cohorts
--      (unenrolled, shadow_only, cohort_5, cohort_25, cohort_100, cohort_ga).
--      The coach-initiated enrollment dialog needs three additional labels
--      that map to the deployment tiers Dr. Nevedal selects from at the
--      bedside: inspection_test (zero-telemetry screen evaluation), pilot_5
--      (the original cohort_5 by its public name), general_availability
--      (the original cohort_ga by its public name). The original 6 labels
--      remain valid; this is purely additive.
--
--   2. sensitive_bridge_log.event_type CHECK extended to include
--      'enrollment_created'
--      ----------------------------------------------------------------
--      Path C emits one new event type when a coach successfully enrolls a
--      client. Per migration 202's header note, adding a new event_type
--      requires DROP CONSTRAINT + ADD CONSTRAINT in a follow-up migration.
--      The original 33 + M215's 'sensitive_profile_screen_opened' = 34
--      event types remain valid; this is purely additive.
--
-- Idempotent: DO-block guards on both constraint replacements. Re-running
-- this migration is a no-op once it has been applied.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. sensitive_bridge_enrollment.cohort_label CHECK extension
--
--    Drop the M209 constraint and re-add with the original 6 labels plus the
--    3 coach-facing labels. The dialog's dropdown maps directly to these
--    enum values; no translation layer in the API.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conname = 'sensitive_bridge_enrollment_cohort_label_check'
           AND conrelid = 'sensitive_bridge_enrollment'::regclass
    ) THEN
        ALTER TABLE sensitive_bridge_enrollment
            DROP CONSTRAINT sensitive_bridge_enrollment_cohort_label_check;
    END IF;

    ALTER TABLE sensitive_bridge_enrollment
        ADD CONSTRAINT sensitive_bridge_enrollment_cohort_label_check
        CHECK (cohort_label IN (
            -- Original 6 (M209) — operational rollout tiers
            'unenrolled',
            'shadow_only',
            'cohort_5',
            'cohort_25',
            'cohort_100',
            'cohort_ga',
            -- Path C (M216) — coach-facing dialog labels
            'inspection_test',
            'pilot_5',
            'general_availability'
        ));
END
$$;

COMMENT ON CONSTRAINT sensitive_bridge_enrollment_cohort_label_check
    ON sensitive_bridge_enrollment IS
    'Canonical cohort labels for the Sensitive Clinical Bridge. The first 6 '
    'are operational rollout tiers (M209). The last 3 (M216) are coach-facing '
    'labels surfaced in the SensitiveClinicalProfileScreen enrollment dialog: '
    'inspection_test (zero-telemetry screen eval), pilot_5 (= cohort_5 by '
    'public name), general_availability (= cohort_ga by public name).';

-- ---------------------------------------------------------------------------
-- 2. sensitive_bridge_log.event_type CHECK extension
--
--    Adds 'enrollment_created' to the canonical event-type catalog.
--    Preserves the original 33 (M202+followups) plus M215's
--    'sensitive_profile_screen_opened' = 34, then appends the new type.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conname = 'sensitive_bridge_log_event_type_check'
           AND conrelid = 'sensitive_bridge_log'::regclass
    ) THEN
        ALTER TABLE sensitive_bridge_log
            DROP CONSTRAINT sensitive_bridge_log_event_type_check;
    END IF;

    ALTER TABLE sensitive_bridge_log
        ADD CONSTRAINT sensitive_bridge_log_event_type_check
        CHECK (event_type IN (
            -- ── original 33 (M202 baseline) ───────────────────────────────
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
            -- ── prior incremental additions preserved ─────────────────────
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
            -- ── M215 addition ─────────────────────────────────────────────
            'sensitive_profile_screen_opened',
            -- ── M216 addition (Path C) ────────────────────────────────────
            'enrollment_created'
        ));
END
$$;

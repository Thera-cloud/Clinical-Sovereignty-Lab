-- ============================================================================
-- Migration 209 — Sensitive Clinical Bridge feature flags + cohort enrollment
-- ============================================================================
--
-- Phase 4 wiring step (plan v1.3 Gap F + Gap H). Ships THREE artifacts that
-- together form the rollout safety mechanism for the Sensitive Clinical Bridge:
--
--   1. app_settings              — global key/value, master kill switch lives here.
--   2. sensitive_bridge_enrollment — per-user cohort + per-user gap-flag overrides.
--   3. detector_telemetry        — false-positive aggregator (auto-disable input).
--
-- IMPORTANT: every flag DEFAULTS TO FALSE at first apply.  No survivor sees v1.3
-- behavior on day-one of deploy.  Even if individual flags are flipped per-user,
-- `app_settings.sensitive_bridge_master_enabled = FALSE` short-circuits the
-- orchestrator's evaluate_disclosure() to a neutral BridgeDecision.  This is the
-- entire safety thesis; do NOT default any flag to TRUE here.
--
-- AUTO-DISABLE TRIGGER STATUS at first apply: INACTIVE-UNTIL-PILOT.
--   The detector_telemetry false-positive aggregator (>5% over trailing 7 days,
--   sample size >=20) is implemented in Phase 6 and only fires after pilot
--   cohort_5 has been live for 7+ days.  The table ships writable but empty.
-- ============================================================================

BEGIN;

-- ────────────────────────────────────────────────────────────────────────────
-- 1. app_settings — global key/value store
-- ────────────────────────────────────────────────────────────────────────────
-- A general-purpose key/value table.  Distinct from skyeye_settings (which is
-- social-platform-scoped).  Single source of truth for cross-system kill
-- switches and global toggles.
CREATE TABLE IF NOT EXISTS app_settings (
    setting_key       TEXT PRIMARY KEY,
    setting_value     JSONB NOT NULL,
    description       TEXT,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by        TEXT
);

COMMENT ON TABLE app_settings IS
    'Global key/value settings store (e.g., master kill switches, feature flags).';

-- Master kill switch — controls whether evaluate_disclosure() runs at all.
-- FALSE = orchestrator short-circuits to neutral BridgeDecision (register_directive=None).
-- This is the rollback mechanism if anything goes wrong with the wiring.
INSERT INTO app_settings (setting_key, setting_value, description, updated_by)
VALUES (
    'sensitive_bridge_master_enabled',
    'false'::jsonb,
    'Master kill switch for Sensitive Clinical Bridge orchestrator. '
    'FALSE = evaluate_disclosure() returns neutral BridgeDecision; '
    'TRUE = full pipeline runs (still subject to per-user gap flags).',
    'migration_209'
)
ON CONFLICT (setting_key) DO NOTHING;

-- Per-gap global default flags.  These are the rollout-wide defaults.
-- Per-user overrides live in sensitive_bridge_enrollment.gap_features_enabled.
-- User-level flag wins over global flag (per Gap F rollout playbook).
INSERT INTO app_settings (setting_key, setting_value, description, updated_by)
VALUES (
    'sensitive_bridge_global_gap_flags',
    '{
        "gap_introjection_enabled": false,
        "gap_thalamic_gate_enabled": false,
        "gap_reengagement_enabled": false,
        "gap_arousal_cap_enabled": false,
        "gap_polyvictim_load_enabled": false,
        "gap_dual_diagnosis_enabled": false,
        "gap_active_disclosure_enabled": false,
        "gap_codeword_enabled": false,
        "gap_trigger_dates_enabled": false,
        "gap_legal_status_enabled": false,
        "gap_embodiment_phase_enabled": false,
        "gap_jurisdiction_compliance_enabled": false,
        "gap_minor_survivor_protections_enabled": false,
        "gap_parenting_no_pathologization_enabled": false,
        "gap_rj_companioning_enabled": false,
        "gap_cultural_context_enabled": false
    }'::jsonb,
    '16 gap-specific feature flags (Gap F rollout playbook). All FALSE at first '
    'apply. Per-user overrides via sensitive_bridge_enrollment.gap_features_enabled.',
    'migration_209'
)
ON CONFLICT (setting_key) DO NOTHING;


-- ────────────────────────────────────────────────────────────────────────────
-- 2. sensitive_bridge_enrollment — per-user cohort phasing + flag overrides
-- ────────────────────────────────────────────────────────────────────────────
-- A user is "enrolled" in v1.3 behavior only when they have a row here AND the
-- master kill switch is TRUE.  cohort_label drives Gap H phasing:
--   cohort_5    — 5 survivors, explicit clinician oversight, 7-day window
--   cohort_25   — early adopters, post pilot sign-off
--   cohort_100  — broad rollout
--   cohort_ga   — general availability
CREATE TABLE IF NOT EXISTS sensitive_bridge_enrollment (
    user_id                TEXT PRIMARY KEY,
    cohort_label           TEXT NOT NULL DEFAULT 'unenrolled'
        CHECK (cohort_label IN (
            'unenrolled', 'shadow_only', 'cohort_5', 'cohort_25', 'cohort_100', 'cohort_ga'
        )),
    gap_features_enabled   JSONB NOT NULL DEFAULT '{}'::jsonb,
    enrolled_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    enrolled_by            TEXT,
    last_modified_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_modified_by       TEXT,
    notes                  TEXT
);

CREATE INDEX IF NOT EXISTS idx_sensitive_bridge_enrollment_cohort
    ON sensitive_bridge_enrollment (cohort_label);

COMMENT ON TABLE sensitive_bridge_enrollment IS
    'Per-user enrollment in Sensitive Clinical Bridge v1.3. cohort_label drives '
    'Gap H phasing; gap_features_enabled JSONB stores per-user gap-flag overrides '
    'that win over global flags in app_settings.sensitive_bridge_global_gap_flags.';

COMMENT ON COLUMN sensitive_bridge_enrollment.gap_features_enabled IS
    'Per-user override map. Keys match the 16 gap_*_enabled names in the global '
    'flag set. Missing keys fall back to the global default. Empty {} = follow '
    'all globals (which are all FALSE at first apply).';


-- ────────────────────────────────────────────────────────────────────────────
-- 3. detector_telemetry — per-detector classification log (auto-disable input)
-- ────────────────────────────────────────────────────────────────────────────
-- Each row is a single detector-level classification event.  The aggregator
-- (Phase 6) computes false-positive rate per gap_flag over trailing 7 days
-- with a sample-size floor of 20 events.  Auto-disable trigger inactive at
-- first apply — table ships writable but empty.
CREATE TABLE IF NOT EXISTS detector_telemetry (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             TEXT,
    session_id          TEXT,
    gap_flag            TEXT NOT NULL,
    classification      TEXT NOT NULL
        CHECK (classification IN ('positive', 'negative', 'true_positive',
                                  'false_positive', 'true_negative', 'false_negative')),
    confidence          NUMERIC(5, 4),
    decision_id         BIGINT,
    clinician_reviewed  BOOLEAN NOT NULL DEFAULT FALSE,
    clinician_verdict   TEXT,
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_detector_telemetry_gap_flag_recorded
    ON detector_telemetry (gap_flag, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_detector_telemetry_clinician_review
    ON detector_telemetry (clinician_reviewed, recorded_at DESC)
    WHERE clinician_reviewed = TRUE;

COMMENT ON TABLE detector_telemetry IS
    'Per-detector classification log. Empty at first apply. Phase 6 aggregator '
    'computes FP rate per gap_flag over trailing 7 days (sample size >=20). '
    'Auto-disable trigger INACTIVE-UNTIL-PILOT cohort_5 +7 days.';


-- ────────────────────────────────────────────────────────────────────────────
-- 4. Audit row — record migration apply for sensitive_bridge_log invariants
-- ────────────────────────────────────────────────────────────────────────────
-- Inserted only if sensitive_bridge_log exists (migration 202 already applied).
-- The orchestrator's auditor checks read this row to confirm Phase 4 wiring
-- artifacts shipped.
--
-- NOTE: 'feature_flags_initialized' is added to sensitive_bridge_log.event_type
-- CHECK by migration 210. If 210 has not yet applied, the insert below would
-- violate the CHECK and abort this migration. The DO block guards against that
-- by extending the CHECK in-place if the new value is missing — making 209 +
-- 210 commutative and self-healing on either ordering.
-- access_classification uses 'admin_only_redacted' (the canonical 202 value);
-- 'admin_only' alone is NOT in 202's CHECK and would also abort the insert.
DO $$
DECLARE
    _has_feature_flags_initialized BOOLEAN;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                   WHERE table_name = 'sensitive_bridge_log') THEN
        RETURN;
    END IF;

    -- Check whether the event_type CHECK already permits 'feature_flags_initialized'.
    SELECT EXISTS (
        SELECT 1
        FROM   pg_constraint
        WHERE  conname = 'sensitive_bridge_log_event_type_check'
          AND  pg_get_constraintdef(oid) ILIKE '%feature_flags_initialized%'
    ) INTO _has_feature_flags_initialized;

    -- If migration 210 has not yet extended the CHECK, extend it inline so this
    -- migration can complete without depending on apply order.
    IF NOT _has_feature_flags_initialized THEN
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
                'auto_disable_reenabled'
            ));
    END IF;

    INSERT INTO sensitive_bridge_log (
        user_id, event_type, event_severity,
        payload_json, recorded_by, access_classification, pii_screened_at
    ) VALUES (
        'system',
        'feature_flags_initialized',
        'info',
        jsonb_build_object(
            'migration', '209_sensitive_bridge_feature_flags',
            'master_enabled_default', false,
            'gap_flags_count', 16,
            'all_flags_default', false,
            'cohort_at_apply', 'unenrolled',
            'detector_telemetry_writable', true,
            'detector_telemetry_row_count_at_apply', 0,
            'auto_disable_trigger_active', false
        ),
        'migration_209',
        'admin_only_redacted',
        NOW()
    );
END$$;

COMMIT;

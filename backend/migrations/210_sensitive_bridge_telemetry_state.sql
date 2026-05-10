-- ============================================================================
-- Migration 210 — Sensitive Clinical Bridge: telemetry agent state + auto-disable
-- ============================================================================
--
-- Phase 5 wiring step. Adds the durable state the
-- `sensitive_bridge_telemetry_agent` needs to implement Plan v1.3 §Gap F
-- auto-disable WITH the three Note 1 safeguards:
--
--   1. MULTI-WINDOW AGREEMENT
--      false_positive_rate computed across THREE trailing windows
--      (24h, 72h, 7d). Auto-disable arms only when ALL THREE windows
--      agree on threshold breach (rate > 0.05 AND clinician_reviewed
--      sample size >= 20 in each window). Single-window breach without
--      multi-window agreement = noise → no action.
--
--   2. ALERT + COUNTDOWN BEFORE DISABLE
--      Plan said "auto-disable then alert"; safer is "alert + 30-minute
--      countdown to disable + admin can cancel". This table holds the
--      countdown state (`armed_at`, `commit_after`, `cancelled_at`).
--      The agent commits the disable only when `commit_after <= NOW()`
--      AND `cancelled_at IS NULL`.
--
--   3. RE-ENABLE REQUIRES RESOLVED TELEMETRY
--      Re-enabling a flag that was auto-disabled is gated on fresh
--      detector_telemetry showing the FP rate now under threshold across
--      a fresh sample (>=20 reviewed events post `disabled_at`). The
--      gate is enforced in the REST handler via the helper
--      `assert_reenable_telemetry_resolved()` and audited by the new
--      auditor slot `auto_disable_reenable_requires_resolved_telemetry`.
--
-- Also extends `sensitive_bridge_log.event_type` CHECK to allow the four
-- auto-disable lifecycle events + the `feature_flags_initialized` event
-- that migration 209 already references but 202's CHECK never permitted
-- (latent bug fix; idempotent re-apply of 209 audit row will succeed
-- after this migration).
--
-- Adds two app_settings rows the agent + auditor read at runtime:
--
--   * sensitive_log_retention_years     — backs the existing auditor slot
--                                          `sensitive_log_retention_default_7yr`
--                                          (was previously unset → warning).
--   * sensitive_bridge_telemetry_agent  — agent config: poll interval,
--                                          countdown duration, threshold,
--                                          window definitions, sample floor.
--
-- AUTO-DISABLE STATUS at first apply: ARMED-BUT-NEUTRAL.
--   The agent ships with `paused = TRUE` in its config row. Pilot launch
--   flips `paused = FALSE` after cohort_5 has been live for 7+ days
--   (per `docs/SENSITIVE_BRIDGE_ROLLOUT_PLAYBOOK.md` §6).
-- ============================================================================

BEGIN;

-- ────────────────────────────────────────────────────────────────────────────
-- 1. Extend sensitive_bridge_log.event_type CHECK
-- ────────────────────────────────────────────────────────────────────────────
-- Adds 5 new event types:
--   * feature_flags_initialized  — already used by migration 209, fixes
--                                  latent constraint mismatch.
--   * auto_disable_armed         — telemetry agent started countdown.
--   * auto_disable_committed     — countdown expired without override; flag off.
--   * auto_disable_cancelled     — admin cancelled before commit_after.
--   * auto_disable_reenabled     — admin re-enabled with resolved telemetry.
--
-- Re-create the constraint with the union (drop-then-add since CHECK lists
-- can't be additively extended in PG without redefining).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'sensitive_bridge_log'
    ) THEN
        ALTER TABLE sensitive_bridge_log
            DROP CONSTRAINT IF EXISTS sensitive_bridge_log_event_type_check;
        ALTER TABLE sensitive_bridge_log
            ADD CONSTRAINT sensitive_bridge_log_event_type_check
            CHECK (event_type IN (
                -- 33 events from migration 202 (preserved exactly)
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
                -- New in migration 210 (5 events for telemetry agent + 209 fix)
                'feature_flags_initialized',
                'auto_disable_armed',
                'auto_disable_committed',
                'auto_disable_cancelled',
                'auto_disable_reenabled'
            ));
    END IF;
END$$;

COMMENT ON COLUMN sensitive_bridge_log.event_type IS
    'Append-only event taxonomy. Extended by migration 210 with the 4 '
    'auto_disable_* lifecycle events (Plan v1.3 Note 1 safeguards) and '
    'feature_flags_initialized (migration 209 audit row event).';


-- ────────────────────────────────────────────────────────────────────────────
-- 2. detector_auto_disable_state — countdown + lifecycle per gap_flag
-- ────────────────────────────────────────────────────────────────────────────
-- One row per gap_flag in active auto-disable lifecycle (armed/disabled).
-- Rows are NEVER deleted; they are append-only state changes mutating the
-- in-place row. The full audit trail lives in `sensitive_bridge_log` events
-- (auto_disable_armed, auto_disable_committed, auto_disable_cancelled,
-- auto_disable_reenabled).
CREATE TABLE IF NOT EXISTS detector_auto_disable_state (
    gap_flag                    TEXT PRIMARY KEY,
    state                       TEXT NOT NULL DEFAULT 'idle'
        CHECK (state IN ('idle', 'armed', 'disabled', 'reenabled')),

    -- Multi-window snapshot at arming time (Note 1 safeguard #1).
    -- JSONB shape: {"24h": {"rate": 0.07, "fp": 5, "reviewed": 60},
    --               "72h": {"rate": 0.06, "fp": 12, "reviewed": 180},
    --               "7d":  {"rate": 0.06, "fp": 30, "reviewed": 460}}
    fp_snapshot_at_arming       JSONB,

    -- Countdown timing (Note 1 safeguard #2).
    armed_at                    TIMESTAMPTZ,
    commit_after                TIMESTAMPTZ,           -- = armed_at + countdown_minutes
    cancelled_at                TIMESTAMPTZ,
    cancelled_by                TEXT,
    cancellation_reason         TEXT,

    -- Disable lifecycle.
    disabled_at                 TIMESTAMPTZ,
    disabled_by                 TEXT,                  -- 'telemetry_agent' or admin id
    disabled_reason             TEXT,

    -- Re-enable lifecycle (Note 1 safeguard #3).
    reenabled_at                TIMESTAMPTZ,
    reenabled_by                TEXT,
    reenable_telemetry_snapshot JSONB,                 -- evidence required to re-enable

    last_observed_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_modified_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_detector_auto_disable_state_state
    ON detector_auto_disable_state (state);
CREATE INDEX IF NOT EXISTS idx_detector_auto_disable_state_armed
    ON detector_auto_disable_state (commit_after)
    WHERE state = 'armed';

COMMENT ON TABLE detector_auto_disable_state IS
    'Per-gap_flag countdown + lifecycle for telemetry agent auto-disable. '
    'Plan v1.3 §Gap F + Phase 5 Note 1 safeguards. Append-only audit trail '
    'lives in sensitive_bridge_log (auto_disable_* event types); this table '
    'holds the in-flight state.';

COMMENT ON COLUMN detector_auto_disable_state.fp_snapshot_at_arming IS
    'Multi-window snapshot recorded at the moment auto-disable was armed. '
    'Required for forensics and for the resolved-telemetry re-enable gate.';

COMMENT ON COLUMN detector_auto_disable_state.commit_after IS
    'Earliest time at which the disable will be committed if not cancelled. '
    'Default = armed_at + 30 min (configurable via app_settings).';

COMMENT ON COLUMN detector_auto_disable_state.reenable_telemetry_snapshot IS
    'Snapshot of the telemetry that satisfied the re-enable resolved-telemetry '
    'gate (Plan v1.3 Note 1 safeguard #3). NULL if never re-enabled.';

-- Update last_modified_at on any change.
CREATE OR REPLACE FUNCTION _touch_auto_disable_state() RETURNS TRIGGER AS $$
BEGIN
    NEW.last_modified_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_touch_auto_disable_state
    ON detector_auto_disable_state;
CREATE TRIGGER trg_touch_auto_disable_state
    BEFORE UPDATE ON detector_auto_disable_state
    FOR EACH ROW EXECUTE FUNCTION _touch_auto_disable_state();


-- ────────────────────────────────────────────────────────────────────────────
-- 3. app_settings.sensitive_log_retention_years
-- ────────────────────────────────────────────────────────────────────────────
-- Backs auditor slot `sensitive_log_retention_default_7yr`. Was previously
-- absent → that auditor slot reported `warning: app_settings.sensitive_log_
-- retention_years not set`. Set the canonical 7-year minimum here so the
-- auditor turns green at first apply.
INSERT INTO app_settings (setting_key, setting_value, description, updated_by)
VALUES (
    'sensitive_log_retention_years',
    '7'::jsonb,
    'Minimum retention for sensitive_bridge_log rows in years. Backs auditor '
    'check sensitive_log_retention_default_7yr. Per-jurisdiction extensions '
    'land in Phase 4 (Gap L) via the trigger sensitive_log_jurisdiction_trigger.',
    'migration_210'
)
ON CONFLICT (setting_key) DO NOTHING;


-- ────────────────────────────────────────────────────────────────────────────
-- 4. app_settings.sensitive_bridge_telemetry_agent — agent runtime config
-- ────────────────────────────────────────────────────────────────────────────
-- The telemetry agent reads this row each cycle. Editing this row is the
-- canonical way to retune the auto-disable safeguards without a code change.
INSERT INTO app_settings (setting_key, setting_value, description, updated_by)
VALUES (
    'sensitive_bridge_telemetry_agent',
    '{
        "paused":                          true,
        "poll_interval_seconds":           3600,
        "countdown_minutes":               30,
        "fp_rate_threshold":               0.05,
        "min_reviewed_sample_per_window":  20,
        "min_reviewed_sample_for_reenable": 20,
        "windows": [
            {"label": "24h", "interval": "24 hours"},
            {"label": "72h", "interval": "72 hours"},
            {"label": "7d",  "interval": "7 days"}
        ],
        "all_windows_must_agree":          true,
        "stagger_seconds":                 320
    }'::jsonb,
    'sensitive_bridge_telemetry_agent runtime config. paused=TRUE at first '
    'apply (ARMED-BUT-NEUTRAL); flip to FALSE after pilot cohort_5 +7 days. '
    'Phase 5 Note 1 safeguards: multi-window agreement (24h/72h/7d), 30-min '
    'countdown with admin override, resolved-telemetry re-enable gate.',
    'migration_210'
)
ON CONFLICT (setting_key) DO NOTHING;


-- ────────────────────────────────────────────────────────────────────────────
-- 5. Audit row — record migration apply
-- ────────────────────────────────────────────────────────────────────────────
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_name = 'sensitive_bridge_log') THEN
        INSERT INTO sensitive_bridge_log (
            user_id, event_type, event_severity,
            payload_json, recorded_by, access_classification, pii_screened_at
        ) VALUES (
            'system',
            'feature_flags_initialized',
            'info',
            jsonb_build_object(
                'migration', '210_sensitive_bridge_telemetry_state',
                'detector_auto_disable_state_created', true,
                'sensitive_log_retention_years_seeded', 7,
                'telemetry_agent_paused_at_apply', true,
                'event_type_check_extended', jsonb_build_array(
                    'feature_flags_initialized',
                    'auto_disable_armed',
                    'auto_disable_committed',
                    'auto_disable_cancelled',
                    'auto_disable_reenabled'
                ),
                'note1_safeguards', jsonb_build_array(
                    'multi_window_agreement_24h_72h_7d',
                    'thirty_minute_countdown_with_admin_override',
                    'reenable_requires_resolved_telemetry_post_disabled_at'
                ),
                'auto_disable_trigger_active', false
            ),
            'migration_210',
            'admin_only_redacted',
            NOW()
        );
    END IF;
END$$;

COMMIT;

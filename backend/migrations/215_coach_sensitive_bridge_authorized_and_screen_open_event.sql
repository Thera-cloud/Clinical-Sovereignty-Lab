-- =============================================================================
-- Migration 215: Coach Sensitive-Bridge Authorization Flag
--                + sensitive_profile_screen_opened audit event type
--
-- This migration unlocks the production entry point to
-- `SensitiveClinicalProfileScreen` from the Coach Command → Briefings tab →
-- "View Brief" modal. Three concerns are folded into one migration because
-- they are functionally inseparable: a coach without the flag must not see
-- the button, the screen-open event must be auditable, and the auditor must
-- be able to assert both gates from a single trust baseline entry.
--
--   1. coach_profiles.coach_sensitive_bridge_authorized BOOLEAN DEFAULT FALSE
--      ----------------------------------------------------------------
--      Independent from `clinician_authorization_type` (migration 214).
--      `clinician_authorization_type` controls how a clinician APPROVES
--      sole-lead-mode mutations; this flag controls whether they can VIEW
--      the sensitive profile surface at all. Default FALSE = closed by
--      default (the safe answer for a 7-year-retention clinical surface).
--
--   2. sensitive_bridge_log.event_type CHECK constraint extended to add
--      'sensitive_profile_screen_opened'
--      ----------------------------------------------------------------
--      Per the migration 202 header note ("Adding a new event_type
--      requires (a) ALTER TABLE … DROP CONSTRAINT + ADD CONSTRAINT in a
--      follow-up migration"), we drop the existing CHECK and re-add it
--      with the additional event type appended. The original 33 event
--      types are preserved verbatim — this is purely additive.
--
--   3. v_clinician_authorization_mode view extended to surface the new
--      flag alongside the existing authorization_type.
--      ----------------------------------------------------------------
--      The view is the auditor's shared read path for both gates. Adding
--      the column keeps the JOIN cheap and lets the auditor confirm both
--      properties from a single SELECT.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS, DO-block guards on constraint
-- creation, CREATE OR REPLACE VIEW. Re-running this migration is a no-op
-- once it has been applied.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. coach_profiles.coach_sensitive_bridge_authorized
-- ---------------------------------------------------------------------------
ALTER TABLE coach_profiles
    ADD COLUMN IF NOT EXISTS coach_sensitive_bridge_authorized BOOLEAN
        NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN coach_profiles.coach_sensitive_bridge_authorized IS
    'Coach Command visibility gate for the Sensitive Clinical Bridge surface. '
    'When TRUE, the "Sensitive Profile" button renders inside the Briefings '
    'tab View Brief modal (disabled until the client is also enrolled in '
    'sensitive_bridge_enrollment). When FALSE (the default), the button is '
    'hidden entirely and no audit row is written even if the client is '
    'enrolled. Independent from clinician_authorization_type (migration 214) '
    'which governs sole-lead approval rights, not viewing rights.';

-- Backfill: grant the lead coach (CoachN) the authorization flag. We use
-- the same target-resolution strategy as migration 214 so the two flags
-- always co-locate on the same row in the canonical sole-lead deployment.
WITH target AS (
    SELECT coach_user_id
      FROM coach_profiles
     WHERE username IN ('CoachN', 'DrNevedal1')
     ORDER BY CASE username
                  WHEN 'CoachN' THEN 1
                  WHEN 'DrNevedal1' THEN 2
                  ELSE 3
              END
     LIMIT 1
)
UPDATE coach_profiles cp
   SET coach_sensitive_bridge_authorized = TRUE,
       updated_at = NOW()
  FROM target
 WHERE cp.coach_user_id = target.coach_user_id
   AND cp.coach_sensitive_bridge_authorized IS DISTINCT FROM TRUE;

CREATE INDEX IF NOT EXISTS idx_coach_profiles_sensitive_bridge_authorized
    ON coach_profiles (coach_user_id)
    WHERE coach_sensitive_bridge_authorized = TRUE;

-- ---------------------------------------------------------------------------
-- 2. sensitive_bridge_log.event_type CHECK extension
--
--    Adds 'sensitive_profile_screen_opened' to the canonical event-type
--    catalog. The constraint is dropped and re-added with the original 33
--    event types preserved verbatim plus the one new type appended. Naming
--    follows the existing convention: <surface>_<verb>_<noun>.
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
            -- ── original 33 types (migration 202 baseline) ────────────────
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
            'sensitive_profile_screen_opened'
        ));
END
$$;

-- ---------------------------------------------------------------------------
-- 3. Extend v_clinician_authorization_mode with the new flag.
--    NOTE: CREATE OR REPLACE VIEW only allows ADDING columns at the END;
--    inserting in the middle raises "cannot change name of view column".
--    Drop-and-recreate is safe — the view is read-only and rebuilt below.
-- ---------------------------------------------------------------------------
DROP VIEW IF EXISTS v_clinician_authorization_mode;

CREATE VIEW v_clinician_authorization_mode AS
    SELECT coach_user_id,
           username,
           display_name,
           clinician_authorization_type,
           coach_sensitive_bridge_authorized,
           updated_at
      FROM coach_profiles;

COMMENT ON VIEW v_clinician_authorization_mode IS
    'Read-only projection of coach_profiles consumed by the Sensitive '
    'Clinical Bridge. Surfaces both clinician_authorization_type '
    '(approval mode, migration 214) and coach_sensitive_bridge_authorized '
    '(view-surface gate, migration 215). The auditor reads this view to '
    'confirm both gates are wired and that the canonical sole-lead row '
    'has both flags set.';

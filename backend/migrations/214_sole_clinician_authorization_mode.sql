-- =============================================================================
-- Migration 214: Sole-Clinician Authorization Mode
--
-- Adds an explicit deployment-mode classifier to the coach directory so the
-- Sensitive Clinical Bridge can distinguish between:
--
--   • 'multi_clinician_team'  — the documented default. Every safe_silence
--                               approval and every shadow→live detector
--                               promotion REQUIRES a second human (different
--                               actor, different session). This matches the
--                               original Plan v1.3 §Gap A two-step gate.
--
--   • 'sole_lead'             — a small-practice deviation reserved for the
--                               clinic's lead therapist who carries the
--                               sole-clinician deployment exemption. They
--                               are allowed to be both proposer and approver
--                               on safe_silence (same person, *different*
--                               login session) and to single-sign-off on
--                               detector promotions, *but only with*:
--                                 (1) Existing codeword precondition (b)
--                                 (2) ≥ 48h reflection delay between review
--                                     completion and promotion
--                                 (3) Mandatory ``sole_clinician_override``
--                                     audit flag on every such mutation
--                                 (4) The 30-day auto-revert on safe_silence
--                                     remains in force
--
-- The column lives on ``coach_profiles`` (the actual table; the user-facing
-- spec calls it "coach_profile" — same entity). We do NOT touch the
-- ``users`` table because that table is bridge-cache-managed and would
-- silently roll back JSONB writes (see bridge-cache-db-sovereignty.mdc).
--
-- Backfill: every existing row defaults to 'multi_clinician_team'. The
-- single 'sole_lead' assignment goes to the lead therapist account
-- (Dr. Nevedal — admin role, username 'CoachN' or alternate 'DrNevedal1'
-- if no CoachN row exists). The UPDATE is intentionally narrow so a
-- careless future migration cannot widen the exemption.
--
-- Idempotent: ALTER TABLE … ADD COLUMN IF NOT EXISTS, conditional CHECK
-- constraint creation, UPDATE filtered on existing values only.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. Add the column with explicit default + CHECK constraint
-- ---------------------------------------------------------------------------
ALTER TABLE coach_profiles
    ADD COLUMN IF NOT EXISTS clinician_authorization_type VARCHAR(32)
        NOT NULL DEFAULT 'multi_clinician_team';

-- The CHECK constraint is added in a separate statement so the migration
-- is re-runnable: ADD CONSTRAINT IF NOT EXISTS does not exist on older
-- Postgres versions, so we guard via DO block.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conname = 'coach_profiles_clinician_authorization_type_check'
    ) THEN
        ALTER TABLE coach_profiles
            ADD CONSTRAINT coach_profiles_clinician_authorization_type_check
            CHECK (clinician_authorization_type IN ('sole_lead', 'multi_clinician_team'));
    END IF;
END
$$;

-- Lock the column policy in a comment so a future maintainer sees the
-- semantic constraint before changing the default.
COMMENT ON COLUMN coach_profiles.clinician_authorization_type IS
    'Sensitive Clinical Bridge deployment mode for this clinician. '
    'Default ''multi_clinician_team'' enforces two-clinician approval on '
    'safe_silence and shadow->live promotion. ''sole_lead'' is reserved '
    'for the lead therapist of a sole-clinician practice and grants a '
    'narrow exemption; see playbook §Sole-Clinician Deployment Mode. '
    'Every sole_lead-driven mutation must write '
    'sole_clinician_override=true to sensitive_bridge_log.';

-- ---------------------------------------------------------------------------
-- 2. Backfill the lead therapist
-- ---------------------------------------------------------------------------
-- Strategy: prefer 'CoachN' (the operational coach handle); if that row is
-- missing, fall back to 'DrNevedal1' (the admin handle). Either way, only
-- ONE row is updated. The query is written so re-runs are no-ops once the
-- value is already 'sole_lead'.
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
   SET clinician_authorization_type = 'sole_lead',
       updated_at = NOW()
  FROM target
 WHERE cp.coach_user_id = target.coach_user_id
   AND cp.clinician_authorization_type <> 'sole_lead';

-- ---------------------------------------------------------------------------
-- 3. Visibility helpers — index on the rare value, view for the auditor
-- ---------------------------------------------------------------------------
-- Partial index keeps the lookup cheap because 'sole_lead' is expected to
-- be a single-digit count even in large coach directories.
CREATE INDEX IF NOT EXISTS idx_coach_profiles_sole_lead
    ON coach_profiles (coach_user_id)
    WHERE clinician_authorization_type = 'sole_lead';

-- View consumed by sensitive_profile_api (safe_silence approve) and
-- sensitive_bridge_telemetry_api (feature-flag promotion). Surfacing as a
-- view (not a function) keeps the JOIN cheap and lets the auditor verify
-- it exists with the same _check_view_present helper.
CREATE OR REPLACE VIEW v_clinician_authorization_mode AS
    SELECT coach_user_id,
           username,
           display_name,
           clinician_authorization_type,
           updated_at
      FROM coach_profiles;

COMMENT ON VIEW v_clinician_authorization_mode IS
    'Read-only projection of coach_profiles.clinician_authorization_type '
    'consumed by the Sensitive Clinical Bridge two-step gate '
    '(sensitive_profile_api safe_silence approve) and by the detector '
    'promotion gate (sensitive_bridge_telemetry_api feature-flag). The '
    'view fixes the column set the application depends on so future '
    'additions to coach_profiles do not break the lookup.';

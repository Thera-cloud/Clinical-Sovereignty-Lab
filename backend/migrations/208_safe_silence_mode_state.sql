-- Migration 208: safe_silence_mode_state seed
-- Plan: Gap A — Two-Step Gate on safe_silence_mode
--       Gap M — 25-day expiry warning + auto-revert
-- Depends on: 202 (sensitive_bridge_log), 204 (codeword precondition)
--
-- safe_silence_mode_state lives inside users.profile_data JSONB. This migration:
--   1. Seeds the JSONB key with the initial inactive state for every existing user.
--   2. Folds in the v1.3 amendment (Gap M expiry_warning_sent_at field) so the
--      structure matches the final v1.3 shape from the start. Since this is
--      seeded for the first time, there is no production data to amend separately.
--
-- JSONB structure:
-- {
--   "state": "inactive" | "pending_approval" | "active",
--   "proposer_id": "<coach_username>" | null,
--   "approver_id": "<admin_username>" | null,
--   "proposed_at": "<iso8601>" | null,
--   "approved_at": "<iso8601>" | null,
--   "expires_at": "<iso8601>" | null,            -- approved_at + 30 days
--   "expiry_warning_sent_at": "<iso8601>" | null, -- Gap M: set at approved_at + 25 days
--   "auto_revert_eligible_at": "<iso8601>" | null, -- Gap M: same as expires_at
--   "codeword_precondition_met": true | false,
--   "reason_redacted": "<short clinical reason>" | null
-- }
--
-- IDEMPOTENT: only seeds rows whose profile_data lacks safe_silence_mode_state.
--
-- BACKFILL SCOPE (production audit, 2026-05-08):
-- This is the FIRST introduction of safe_silence_mode_state in production.
-- No prior implementation exists, so no rows have state='active' or state='pending_approval'.
-- This seed initializes every row to the inactive state with the v1.3 shape.
--
-- IF a future audit reveals any pre-seed 'active' or 'pending_approval' rows
-- (e.g., from a manual JSONB write), run this corrective UPDATE before Gap M's
-- daily scan goes live:
--
--   UPDATE users
--   SET profile_data = jsonb_set(
--     profile_data,
--     '{safe_silence_mode_state,auto_revert_eligible_at}',
--     to_jsonb(((profile_data->'safe_silence_mode_state'->>'approved_at')::TIMESTAMP
--               WITH TIME ZONE + INTERVAL '30 days')::text)
--   )
--   WHERE profile_data->'safe_silence_mode_state'->>'state' = 'active'
--     AND profile_data->'safe_silence_mode_state'->>'auto_revert_eligible_at' IS NULL;
--
-- The same pattern applies to expires_at if NULL on an active row.

UPDATE users
SET profile_data = jsonb_set(
  COALESCE(profile_data, '{}'::jsonb),
  '{safe_silence_mode_state}',
  jsonb_build_object(
    'state', 'inactive',
    'proposer_id', NULL,
    'approver_id', NULL,
    'proposed_at', NULL,
    'approved_at', NULL,
    'expires_at', NULL,
    'expiry_warning_sent_at', NULL,
    'auto_revert_eligible_at', NULL,
    'codeword_precondition_met', false,
    'reason_redacted', NULL
  ),
  true
)
WHERE profile_data->>'safe_silence_mode_state' IS NULL
   OR jsonb_typeof(profile_data->'safe_silence_mode_state') != 'object';

-- Verification view (read-only) for clinician dashboards / auditor checks.
-- Uses CREATE OR REPLACE so re-applying is safe.
CREATE OR REPLACE VIEW safe_silence_mode_active_users AS
SELECT
  username,
  profile_data->'safe_silence_mode_state'->>'state' AS state,
  profile_data->'safe_silence_mode_state'->>'approver_id' AS approver_id,
  (profile_data->'safe_silence_mode_state'->>'approved_at')::TIMESTAMP WITH TIME ZONE AS approved_at,
  (profile_data->'safe_silence_mode_state'->>'expires_at')::TIMESTAMP WITH TIME ZONE AS expires_at,
  (profile_data->'safe_silence_mode_state'->>'expiry_warning_sent_at')::TIMESTAMP WITH TIME ZONE
    AS expiry_warning_sent_at
FROM users
WHERE profile_data->'safe_silence_mode_state'->>'state' IN ('pending_approval','active');

COMMENT ON VIEW safe_silence_mode_active_users IS
  'Read-only view of users currently in pending_approval or active safe_silence_mode. '
  'Used by nate_checkin_agent daily scan (Gap M) and sensitive_bridge_auditor checks.';

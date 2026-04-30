-- Migration 109: Backfill coach_assignments from existing profile_data
--
-- Background:
--   Migration 083 created the coach_assignments junction table but did NOT
--   backfill it from the pre-existing primary-coach designations stored in
--   users.profile_data->>'assigned_coach_id'. The 3 INSERT paths
--   (admin.py, bridge_server.py:12620, corporate_command_api.py) only run
--   on NEW assignments, so every client assigned BEFORE migration 083 has
--   no row in coach_assignments.
--
-- Symptom:
--   Coach Portal handlers that gate on coach_assignments
--   (coach_get_client_panel_insights at bridge_server.py:17617,
--    coach_set/get/clear_client_override + coach_get_override_history +
--    coach_renew_override at bridge_server.py:17866) return
--   {"type":"error","message":"NOT_ASSIGNED_COACH"} for every existing
--   client when the caller is COACH (not ADMIN). The Coach Portal renders
--   the literal "Error: NOT_ASSIGNED_COACH" snackbar.
--
-- Fix:
--   Backfill coach_assignments from users.profile_data->>'assigned_coach_id'
--   for every CLIENT that has a non-empty assignment. Idempotent via the
--   existing UNIQUE constraint (coach_id, entity_type, entity_id).
--
-- Safety:
--   - Read-only against users; only INSERT into coach_assignments.
--   - ON CONFLICT DO NOTHING — re-running is a no-op.
--   - Marks every backfilled row as is_primary=true (matches the semantic
--     of "primary coach designation" defined in 083_coach_assignments.sql).
--   - assigned_by='migration_109_backfill' so future audits can identify
--     historical rows vs runtime ones.

INSERT INTO coach_assignments (coach_id, entity_type, entity_id, is_primary, assigned_by)
SELECT
    profile_data->>'assigned_coach_id'  AS coach_id,
    'client'                            AS entity_type,
    hardware_id                         AS entity_id,
    TRUE                                AS is_primary,
    'migration_109_backfill'            AS assigned_by
FROM users
WHERE role = 'CLIENT'
  AND hardware_id IS NOT NULL
  AND hardware_id <> ''
  AND profile_data->>'assigned_coach_id' IS NOT NULL
  AND profile_data->>'assigned_coach_id' <> ''
ON CONFLICT (coach_id, entity_type, entity_id) DO NOTHING;

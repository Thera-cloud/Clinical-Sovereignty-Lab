-- Migration 195: Backfill family_members from users.family_id (PGSD / junction parity)
--
-- Background:
--   Users are linked to households via users.family_id (UUID, indexed). The
--   family_members table (migration 029, extended by migration 177) exists
--   as the junction rows some code expects. Runtime paths that only update
--   users.family_id left family_members empty for historical accounts.
--
-- Symptom:
--   PGSD Section VII "Family Entanglement" computes empty member sets because
--   _handle_get_family_entanglement loads membership only from family_members
--   (websocket/pgsd_handlers.py _load_family_members), while the PGSD dropdown
--   lists families sourced from profiles with users.family_id set.
--
-- Fix:
--   INSERT one family_members row per user with a non-null family_id, using
--   text keys consistent with handlers (family_id::text, id::text for user).
--
-- Idempotency:
--   Implemented with NOT EXISTS over (family_id, user_id) because legacy /
--   split-definition schemas did not reliably define a UNIQUE on that pair.
--   Safe to re-run; repeat runs insert nothing.
--
-- Safety:
--   Read-only against users outside this INSERT predicate; INSERT only into
--   family_members. Skips soft-deleted users (deleted_at IS NOT NULL).
--   Does not UPDATE or DELETE existing rows.

INSERT INTO family_members (family_id, user_id)
SELECT DISTINCT
    trim(u.family_id::text) AS family_id,
    u.id::text AS user_id
FROM users u
WHERE u.family_id IS NOT NULL
  AND deleted_at IS NULL
  AND length(trim(u.family_id::text)) > 0
  AND NOT EXISTS (
      SELECT 1
      FROM family_members fm
      WHERE trim(fm.family_id) = trim(u.family_id::text)
        AND fm.user_id = u.id::text
    );

-- =============================================================================
-- Accounts: EricBando (HEAD), client_SelenaBando (SPOUSE).
-- Preconditions: verify usernames with:
--   SELECT username, hardware_id, role,
--          profile_data->>'family_id', profile_data->>'family_role', family_id
--   FROM users WHERE username ILIKE '%bando%' AND role = 'CLIENT';
-- After run: restart nate_bridge so registry reloads from PostgreSQL.
-- =============================================================================

BEGIN;

INSERT INTO families (family_code)
VALUES ('FAM_BANDO01')
ON CONFLICT (family_code) DO NOTHING;

WITH fid AS (
    SELECT id FROM families WHERE family_code = 'FAM_BANDO01' LIMIT 1
)
UPDATE users AS u SET
    family_id = (SELECT id FROM fid),
    profile_data = jsonb_set(
        jsonb_set(
            COALESCE(u.profile_data, '{}'::jsonb),
            '{family_id}',
            '"FAM_BANDO01"',
            true
        ),
        '{family_role}',
        CASE
            WHEN lower(u.username) = 'ericbando' THEN '"HEAD"'::jsonb
            WHEN lower(u.username) = 'client_selenaando' THEN '"SPOUSE"'::jsonb
            ELSE COALESCE(u.profile_data->'family_role', '"MEMBER"'::jsonb)
        END,
        true
    ),
    updated_at = NOW()
WHERE lower(u.username) IN ('ericbando', 'client_selenaando')
  AND u.role = 'CLIENT'
  AND u.deleted_at IS NULL;

COMMIT;

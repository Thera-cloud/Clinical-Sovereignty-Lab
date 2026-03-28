-- Migration 104: Security Hardening — RLS, Least-Privilege Role, DB Audit Hardening
-- Implements:
--   1. nate_app role — non-superuser, least-privilege application role
--   2. Row Level Security on users, vault_folders, vault_items
--   3. Policies that: let nate_admin bypass (existing app unaffected),
--      and restrict nate_app to rows belonging to the authenticated user context
--   4. Audit columns on users table
--
-- SAFETY: nate_admin is a superuser and bypasses RLS by default.
-- Existing app continues to work without any code changes.
-- nate_app policies activate only when the connection role is switched.
-- ============================================================================

-- ============================================================================
-- STEP 1: CREATE nate_app LEAST-PRIVILEGE ROLE
-- ============================================================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'nate_app') THEN
        CREATE ROLE nate_app LOGIN
            PASSWORD 'CHANGE_ME_BEFORE_USE'
            CONNECTION LIMIT 50
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION;

        COMMENT ON ROLE nate_app IS
            'Least-privilege application role. Never superuser. '
            'Connect via DATABASE_URL with this role for defence-in-depth. '
            'nate_admin remains for migrations and maintenance only.';
    END IF;
END;
$$;

-- Grant connect + usage
GRANT CONNECT ON DATABASE little_nate TO nate_app;
GRANT USAGE ON SCHEMA public TO nate_app;

-- Table-level grants (DML only — no DDL, no TRUNCATE, no DROP)
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO nate_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO nate_app;

-- Ensure future tables and sequences are also granted
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO nate_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO nate_app;

-- Explicitly DENY superuser-level operations (belt-and-suspenders)
REVOKE CREATE ON SCHEMA public FROM nate_app;


-- ============================================================================
-- STEP 2: ROW LEVEL SECURITY — users table
-- ============================================================================
-- Enable RLS. nate_admin (superuser) bypasses automatically.
-- nate_app will be bound by policies below.
ALTER TABLE users ENABLE ROW LEVEL SECURITY;

-- Policy: nate_admin (and any superuser) sees all rows — existing app unaffected
-- (Superusers bypass RLS by default, but this makes intent explicit for FORCE RLS future use)
DROP POLICY IF EXISTS users_admin_all ON users;
CREATE POLICY users_admin_all ON users
    AS PERMISSIVE
    FOR ALL
    TO nate_admin
    USING (true)
    WITH CHECK (true);

-- Policy: nate_app can only see/modify a user's own row OR rows where
-- current_setting('app.acting_username', true) matches username.
-- The app sets this via SET LOCAL before queries.
DROP POLICY IF EXISTS users_app_own_row ON users;
CREATE POLICY users_app_own_row ON users
    AS PERMISSIVE
    FOR ALL
    TO nate_app
    USING (
        username = COALESCE(
            current_setting('app.acting_username', true),
            ''
        )
        OR role = 'ADMIN'   -- always allow reading admin rows (for auth checks)
    )
    WITH CHECK (
        username = COALESCE(
            current_setting('app.acting_username', true),
            ''
        )
    );


-- ============================================================================
-- STEP 3: ROW LEVEL SECURITY — vault_folders
-- ============================================================================
ALTER TABLE vault_folders ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS vault_folders_admin_all ON vault_folders;
CREATE POLICY vault_folders_admin_all ON vault_folders
    AS PERMISSIVE FOR ALL TO nate_admin
    USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS vault_folders_app_own ON vault_folders;
CREATE POLICY vault_folders_app_own ON vault_folders
    AS PERMISSIVE FOR ALL TO nate_app
    USING (
        member_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
    )
    WITH CHECK (
        member_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
    );


-- ============================================================================
-- STEP 4: ROW LEVEL SECURITY — vault_items
-- ============================================================================
ALTER TABLE vault_items ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS vault_items_admin_all ON vault_items;
CREATE POLICY vault_items_admin_all ON vault_items
    AS PERMISSIVE FOR ALL TO nate_admin
    USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS vault_items_app_own ON vault_items;
CREATE POLICY vault_items_app_own ON vault_items
    AS PERMISSIVE FOR ALL TO nate_app
    USING (
        member_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
    )
    WITH CHECK (
        member_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
    );


-- ============================================================================
-- STEP 5: ROW LEVEL SECURITY — token_transactions (client isolation)
-- ============================================================================
ALTER TABLE token_transactions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS token_tx_admin_all ON token_transactions;
CREATE POLICY token_tx_admin_all ON token_transactions
    AS PERMISSIVE FOR ALL TO nate_admin
    USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS token_tx_app_own ON token_transactions;
CREATE POLICY token_tx_app_own ON token_transactions
    AS PERMISSIVE FOR ALL TO nate_app
    USING (
        username = COALESCE(current_setting('app.acting_username', true), '')
    )
    WITH CHECK (
        username = COALESCE(current_setting('app.acting_username', true), '')
    );


-- ============================================================================
-- STEP 6: AUDIT COLUMNS — last_login_at, last_login_ip on users
-- ============================================================================
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS last_login_at   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_login_ip   VARCHAR(45),
    ADD COLUMN IF NOT EXISTS failed_login_count INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS locked_until    TIMESTAMPTZ;

COMMENT ON COLUMN users.last_login_at      IS 'Timestamp of most recent successful login';
COMMENT ON COLUMN users.last_login_ip      IS 'IP address of most recent successful login';
COMMENT ON COLUMN users.failed_login_count IS 'Consecutive failed login attempts since last success';
COMMENT ON COLUMN users.locked_until       IS 'Account locked until this timestamp after repeated failures';


-- ============================================================================
-- STEP 7: REVOKE PUBLIC SCHEMA CREATE (PostgreSQL 14 default regression fix)
-- ============================================================================
REVOKE CREATE ON SCHEMA public FROM PUBLIC;


-- ============================================================================
-- STEP 8: INDEX — security event lookup performance
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_users_locked_until
    ON users (locked_until)
    WHERE locked_until IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_users_last_login
    ON users (last_login_at DESC NULLS LAST);


-- ============================================================================
-- STEP 9: RECORD MIGRATION
-- ============================================================================
INSERT INTO security_events (event_type, severity, detail)
VALUES (
    'security_hardening_applied',
    'INFO',
    jsonb_build_object(
        'migration', '104_security_hardening',
        'applied_at', NOW(),
        'changes', jsonb_build_array(
            'nate_app role created (least-privilege)',
            'RLS enabled: users, vault_folders, vault_items, token_transactions',
            'Admin bypass policies: nate_admin sees all rows',
            'App policies: nate_app scoped to app.acting_username / app.acting_hardware_id',
            'Audit columns added: last_login_at, last_login_ip, failed_login_count, locked_until',
            'REVOKE CREATE ON SCHEMA public FROM PUBLIC',
            'Performance indexes: idx_users_locked_until, idx_users_last_login'
        )
    )
) ON CONFLICT DO NOTHING;

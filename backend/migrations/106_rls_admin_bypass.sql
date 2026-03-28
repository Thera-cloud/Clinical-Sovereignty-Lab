-- Migration 106: RLS Admin Bypass for Background Agents
-- Adds COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN' bypass
-- to all nate_app RLS policies so that background agents (auditors, digest,
-- token_usage_agent, etc.) can query across all users when they set
-- app.acting_role = 'ADMIN' via the RLS context middleware.
--
-- Without this, switching DATABASE_URL to nate_app would cause background
-- agents to see zero rows on RLS-protected tables.
-- ============================================================================

-- ============================================================================
-- STEP 1: UPDATE users policy — add admin bypass
-- ============================================================================
DROP POLICY IF EXISTS users_app_own_row ON users;
CREATE POLICY users_app_own_row ON users
    AS PERMISSIVE
    FOR ALL
    TO nate_app
    USING (
        username = COALESCE(current_setting('app.acting_username', true), '')
        OR role = 'ADMIN'
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    )
    WITH CHECK (
        username = COALESCE(current_setting('app.acting_username', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    );


-- ============================================================================
-- STEP 2: UPDATE vault_folders policy — add admin bypass
-- ============================================================================
DROP POLICY IF EXISTS vault_folders_app_own ON vault_folders;
CREATE POLICY vault_folders_app_own ON vault_folders
    AS PERMISSIVE
    FOR ALL
    TO nate_app
    USING (
        member_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    )
    WITH CHECK (
        member_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    );


-- ============================================================================
-- STEP 3: UPDATE vault_items policy — add admin bypass
-- ============================================================================
DROP POLICY IF EXISTS vault_items_app_own ON vault_items;
CREATE POLICY vault_items_app_own ON vault_items
    AS PERMISSIVE
    FOR ALL
    TO nate_app
    USING (
        member_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    )
    WITH CHECK (
        member_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    );


-- ============================================================================
-- STEP 4: UPDATE token_transactions policy — add admin bypass
-- ============================================================================
DROP POLICY IF EXISTS token_tx_app_own ON token_transactions;
CREATE POLICY token_tx_app_own ON token_transactions
    AS PERMISSIVE
    FOR ALL
    TO nate_app
    USING (
        username = COALESCE(current_setting('app.acting_username', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    )
    WITH CHECK (
        username = COALESCE(current_setting('app.acting_username', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    );


-- ============================================================================
-- STEP 5: Grant nate_app SELECT on users_secure view (decrypted reads)
-- ============================================================================
GRANT SELECT ON users_secure TO nate_app;


-- ============================================================================
-- STEP 6: Record migration
-- ============================================================================
INSERT INTO security_events (event_type, severity, detail)
VALUES (
    'rls_admin_bypass_applied',
    'INFO',
    jsonb_build_object(
        'migration', '106_rls_admin_bypass',
        'applied_at', NOW(),
        'changes', jsonb_build_array(
            'Updated users_app_own_row policy: added app.acting_role=ADMIN bypass',
            'Updated vault_folders_app_own policy: added app.acting_role=ADMIN bypass',
            'Updated vault_items_app_own policy: added app.acting_role=ADMIN bypass',
            'Updated token_tx_app_own policy: added app.acting_role=ADMIN bypass',
            'Granted SELECT on users_secure view to nate_app'
        )
    )
) ON CONFLICT DO NOTHING;

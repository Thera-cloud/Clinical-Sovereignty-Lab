-- Migration 107: RLS Phase 2 — Clinical & Session Tables
-- Extends Row Level Security to 5 additional tables containing clinical data.
--
-- Tables:
--   sessions            — UUID user_id/coach_id (FK to users.id)
--   coaching_sessions   — TEXT client_id/coach_id (hardware_id)
--   conversation_history — TEXT user_id (hardware_id)
--   nevedal_metrics     — UUID user_id (FK to users.id)
--   crisis_watchlist    — UUID user_id/assigned_coach_id (FK to users.id)
--
-- Pattern: nate_admin sees all (superuser bypass + explicit policy).
--          nate_app sees own rows + coach-assigned rows + admin bypass.
-- ============================================================================


-- ============================================================================
-- STEP 1: sessions (UUID user_id, UUID coach_id)
-- Client sees own sessions; coach sees sessions they coach.
-- ============================================================================
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS sessions_admin_all ON sessions;
CREATE POLICY sessions_admin_all ON sessions
    AS PERMISSIVE FOR ALL TO nate_admin
    USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS sessions_app_own ON sessions;
CREATE POLICY sessions_app_own ON sessions
    AS PERMISSIVE
    FOR ALL
    TO nate_app
    USING (
        user_id = (
            SELECT id FROM users
            WHERE username = COALESCE(current_setting('app.acting_username', true), '')
            LIMIT 1
        )
        OR coach_id = (
            SELECT id FROM users
            WHERE username = COALESCE(current_setting('app.acting_username', true), '')
            LIMIT 1
        )
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    )
    WITH CHECK (
        user_id = (
            SELECT id FROM users
            WHERE username = COALESCE(current_setting('app.acting_username', true), '')
            LIMIT 1
        )
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    );


-- ============================================================================
-- STEP 2: coaching_sessions (TEXT client_id = hardware_id, TEXT coach_id = hardware_id)
-- Client sees own sessions; coach sees sessions they coach.
-- ============================================================================
ALTER TABLE coaching_sessions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS coaching_sessions_admin_all ON coaching_sessions;
CREATE POLICY coaching_sessions_admin_all ON coaching_sessions
    AS PERMISSIVE FOR ALL TO nate_admin
    USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS coaching_sessions_app_own ON coaching_sessions;
CREATE POLICY coaching_sessions_app_own ON coaching_sessions
    AS PERMISSIVE
    FOR ALL
    TO nate_app
    USING (
        client_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        OR coach_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    )
    WITH CHECK (
        client_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        OR coach_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    );


-- ============================================================================
-- STEP 3: conversation_history (TEXT user_id = hardware_id)
-- User sees only their own conversations.
-- ============================================================================
ALTER TABLE conversation_history ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS convhist_admin_all ON conversation_history;
CREATE POLICY convhist_admin_all ON conversation_history
    AS PERMISSIVE FOR ALL TO nate_admin
    USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS convhist_app_own ON conversation_history;
CREATE POLICY convhist_app_own ON conversation_history
    AS PERMISSIVE
    FOR ALL
    TO nate_app
    USING (
        user_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    )
    WITH CHECK (
        user_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    );


-- ============================================================================
-- STEP 4: nevedal_metrics (UUID user_id FK to users.id)
-- User sees own metrics; admin sees all for research lab.
-- ============================================================================
ALTER TABLE nevedal_metrics ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS nevedal_metrics_admin_all ON nevedal_metrics;
CREATE POLICY nevedal_metrics_admin_all ON nevedal_metrics
    AS PERMISSIVE FOR ALL TO nate_admin
    USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS nevedal_metrics_app_own ON nevedal_metrics;
CREATE POLICY nevedal_metrics_app_own ON nevedal_metrics
    AS PERMISSIVE
    FOR ALL
    TO nate_app
    USING (
        user_id = (
            SELECT id FROM users
            WHERE username = COALESCE(current_setting('app.acting_username', true), '')
            LIMIT 1
        )
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    )
    WITH CHECK (
        user_id = (
            SELECT id FROM users
            WHERE username = COALESCE(current_setting('app.acting_username', true), '')
            LIMIT 1
        )
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    );


-- ============================================================================
-- STEP 5: crisis_watchlist (UUID user_id, UUID assigned_coach_id)
-- Visible to the affected user, their assigned coach, and admins.
-- ============================================================================
ALTER TABLE crisis_watchlist ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS crisis_watchlist_admin_all ON crisis_watchlist;
CREATE POLICY crisis_watchlist_admin_all ON crisis_watchlist
    AS PERMISSIVE FOR ALL TO nate_admin
    USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS crisis_watchlist_app_own ON crisis_watchlist;
CREATE POLICY crisis_watchlist_app_own ON crisis_watchlist
    AS PERMISSIVE
    FOR ALL
    TO nate_app
    USING (
        user_id = (
            SELECT id FROM users
            WHERE username = COALESCE(current_setting('app.acting_username', true), '')
            LIMIT 1
        )
        OR assigned_coach_id = (
            SELECT id FROM users
            WHERE username = COALESCE(current_setting('app.acting_username', true), '')
            LIMIT 1
        )
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    )
    WITH CHECK (
        COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    );


-- ============================================================================
-- STEP 6: Record migration
-- ============================================================================
INSERT INTO security_events (event_type, severity, detail)
VALUES (
    'rls_phase2_clinical_tables',
    'INFO',
    jsonb_build_object(
        'migration', '107_rls_phase2_clinical_tables',
        'applied_at', NOW(),
        'tables', jsonb_build_array(
            'sessions — RLS by user_id (client) + coach_id (coach) UUID',
            'coaching_sessions — RLS by client_id + coach_id hardware_id',
            'conversation_history — RLS by user_id hardware_id',
            'nevedal_metrics — RLS by user_id UUID',
            'crisis_watchlist — RLS by user_id + assigned_coach_id UUID'
        )
    )
) ON CONFLICT DO NOTHING;

-- Migration 108: RLS Tier 1 — Billing, PII, Coach, and Me2Me Tables
-- Adds row-level security to 21 tables containing financial, identity,
-- and clinical ownership data.
--
-- Ownership patterns:
--   A) UUID user_id → subquery through users table
--   B) TEXT hardware_id columns → direct match on app.acting_hardware_id
--   C) TEXT username columns → direct match on app.acting_username
--   D) Indirect FK → subquery through parent table
--
-- All policies include ADMIN bypass via app.acting_role = 'ADMIN'

BEGIN;

-- ============================================================
-- GROUP A: UUID-based ownership (user_id UUID FK to users.id)
-- ============================================================

-- 1. subscriptions
ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;
CREATE POLICY subscriptions_admin_all ON subscriptions
    AS PERMISSIVE FOR ALL TO nate_admin USING (true) WITH CHECK (true);
CREATE POLICY subscriptions_app_own ON subscriptions
    AS PERMISSIVE FOR ALL TO nate_app
    USING (
        user_id = (SELECT id FROM users WHERE username = COALESCE(current_setting('app.acting_username', true), '') LIMIT 1)
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    )
    WITH CHECK (
        user_id = (SELECT id FROM users WHERE username = COALESCE(current_setting('app.acting_username', true), '') LIMIT 1)
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    );

-- 2. subscription_items
ALTER TABLE subscription_items ENABLE ROW LEVEL SECURITY;
CREATE POLICY subscription_items_admin_all ON subscription_items
    AS PERMISSIVE FOR ALL TO nate_admin USING (true) WITH CHECK (true);
CREATE POLICY subscription_items_app_own ON subscription_items
    AS PERMISSIVE FOR ALL TO nate_app
    USING (
        user_id = (SELECT id FROM users WHERE username = COALESCE(current_setting('app.acting_username', true), '') LIMIT 1)
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    )
    WITH CHECK (
        user_id = (SELECT id FROM users WHERE username = COALESCE(current_setting('app.acting_username', true), '') LIMIT 1)
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    );

-- 3. payment_history
ALTER TABLE payment_history ENABLE ROW LEVEL SECURITY;
CREATE POLICY payment_history_admin_all ON payment_history
    AS PERMISSIVE FOR ALL TO nate_admin USING (true) WITH CHECK (true);
CREATE POLICY payment_history_app_own ON payment_history
    AS PERMISSIVE FOR ALL TO nate_app
    USING (
        user_id = (SELECT id FROM users WHERE username = COALESCE(current_setting('app.acting_username', true), '') LIMIT 1)
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    )
    WITH CHECK (
        user_id = (SELECT id FROM users WHERE username = COALESCE(current_setting('app.acting_username', true), '') LIMIT 1)
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    );

-- 4. session_packs
ALTER TABLE session_packs ENABLE ROW LEVEL SECURITY;
CREATE POLICY session_packs_admin_all ON session_packs
    AS PERMISSIVE FOR ALL TO nate_admin USING (true) WITH CHECK (true);
CREATE POLICY session_packs_app_own ON session_packs
    AS PERMISSIVE FOR ALL TO nate_app
    USING (
        user_id = (SELECT id FROM users WHERE username = COALESCE(current_setting('app.acting_username', true), '') LIMIT 1)
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    )
    WITH CHECK (
        user_id = (SELECT id FROM users WHERE username = COALESCE(current_setting('app.acting_username', true), '') LIMIT 1)
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    );


-- ============================================================
-- GROUP B: Hardware-ID-based ownership (text columns)
-- ============================================================

-- 5. coach_folders
ALTER TABLE coach_folders ENABLE ROW LEVEL SECURITY;
CREATE POLICY coach_folders_admin_all ON coach_folders
    AS PERMISSIVE FOR ALL TO nate_admin USING (true) WITH CHECK (true);
CREATE POLICY coach_folders_app_own ON coach_folders
    AS PERMISSIVE FOR ALL TO nate_app
    USING (
        coach_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    )
    WITH CHECK (
        coach_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    );

-- 6. coach_folder_files (owned by uploader or parent folder's coach)
ALTER TABLE coach_folder_files ENABLE ROW LEVEL SECURITY;
CREATE POLICY coach_folder_files_admin_all ON coach_folder_files
    AS PERMISSIVE FOR ALL TO nate_admin USING (true) WITH CHECK (true);
CREATE POLICY coach_folder_files_app_own ON coach_folder_files
    AS PERMISSIVE FOR ALL TO nate_app
    USING (
        uploaded_by = COALESCE(current_setting('app.acting_hardware_id', true), '')
        OR folder_id IN (
            SELECT id FROM coach_folders
            WHERE coach_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        )
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    )
    WITH CHECK (
        uploaded_by = COALESCE(current_setting('app.acting_hardware_id', true), '')
        OR folder_id IN (
            SELECT id FROM coach_folders
            WHERE coach_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        )
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    );

-- 7. client_fcodes (visible to the client AND their assigned coach)
ALTER TABLE client_fcodes ENABLE ROW LEVEL SECURITY;
CREATE POLICY client_fcodes_admin_all ON client_fcodes
    AS PERMISSIVE FOR ALL TO nate_admin USING (true) WITH CHECK (true);
CREATE POLICY client_fcodes_app_own ON client_fcodes
    AS PERMISSIVE FOR ALL TO nate_app
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

-- 8. coach_assignments
ALTER TABLE coach_assignments ENABLE ROW LEVEL SECURITY;
CREATE POLICY coach_assignments_admin_all ON coach_assignments
    AS PERMISSIVE FOR ALL TO nate_admin USING (true) WITH CHECK (true);
CREATE POLICY coach_assignments_app_own ON coach_assignments
    AS PERMISSIVE FOR ALL TO nate_app
    USING (
        coach_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    )
    WITH CHECK (
        coach_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    );

-- 9. me2me_consent_records
ALTER TABLE me2me_consent_records ENABLE ROW LEVEL SECURITY;
CREATE POLICY me2me_consent_records_admin_all ON me2me_consent_records
    AS PERMISSIVE FOR ALL TO nate_admin USING (true) WITH CHECK (true);
CREATE POLICY me2me_consent_records_app_own ON me2me_consent_records
    AS PERMISSIVE FOR ALL TO nate_app
    USING (
        user_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    )
    WITH CHECK (
        user_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    );

-- 10. me2me_imprint_entries
ALTER TABLE me2me_imprint_entries ENABLE ROW LEVEL SECURITY;
CREATE POLICY me2me_imprint_entries_admin_all ON me2me_imprint_entries
    AS PERMISSIVE FOR ALL TO nate_admin USING (true) WITH CHECK (true);
CREATE POLICY me2me_imprint_entries_app_own ON me2me_imprint_entries
    AS PERMISSIVE FOR ALL TO nate_app
    USING (
        user_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    )
    WITH CHECK (
        user_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    );

-- 11. me2me_identity_crystals
ALTER TABLE me2me_identity_crystals ENABLE ROW LEVEL SECURITY;
CREATE POLICY me2me_identity_crystals_admin_all ON me2me_identity_crystals
    AS PERMISSIVE FOR ALL TO nate_admin USING (true) WITH CHECK (true);
CREATE POLICY me2me_identity_crystals_app_own ON me2me_identity_crystals
    AS PERMISSIVE FOR ALL TO nate_app
    USING (
        user_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    )
    WITH CHECK (
        user_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    );

-- 12. me2me_avatars
ALTER TABLE me2me_avatars ENABLE ROW LEVEL SECURITY;
CREATE POLICY me2me_avatars_admin_all ON me2me_avatars
    AS PERMISSIVE FOR ALL TO nate_admin USING (true) WITH CHECK (true);
CREATE POLICY me2me_avatars_app_own ON me2me_avatars
    AS PERMISSIVE FOR ALL TO nate_app
    USING (
        user_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    )
    WITH CHECK (
        user_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    );

-- 13. me2me_growth_layers (indirect via me2me_avatars.avatar_id)
ALTER TABLE me2me_growth_layers ENABLE ROW LEVEL SECURITY;
CREATE POLICY me2me_growth_layers_admin_all ON me2me_growth_layers
    AS PERMISSIVE FOR ALL TO nate_admin USING (true) WITH CHECK (true);
CREATE POLICY me2me_growth_layers_app_own ON me2me_growth_layers
    AS PERMISSIVE FOR ALL TO nate_app
    USING (
        avatar_id IN (
            SELECT avatar_id FROM me2me_avatars
            WHERE user_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        )
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    )
    WITH CHECK (
        avatar_id IN (
            SELECT avatar_id FROM me2me_avatars
            WHERE user_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        )
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    );


-- ============================================================
-- GROUP C: Username-based ownership (varchar columns)
-- ============================================================

-- 14. coach_nate_chat_history
ALTER TABLE coach_nate_chat_history ENABLE ROW LEVEL SECURITY;
CREATE POLICY coach_nate_chat_history_admin_all ON coach_nate_chat_history
    AS PERMISSIVE FOR ALL TO nate_admin USING (true) WITH CHECK (true);
CREATE POLICY coach_nate_chat_history_app_own ON coach_nate_chat_history
    AS PERMISSIVE FOR ALL TO nate_app
    USING (
        coach_username = COALESCE(current_setting('app.acting_username', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    )
    WITH CHECK (
        coach_username = COALESCE(current_setting('app.acting_username', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    );

-- 15. gkm_donations
ALTER TABLE gkm_donations ENABLE ROW LEVEL SECURITY;
CREATE POLICY gkm_donations_admin_all ON gkm_donations
    AS PERMISSIVE FOR ALL TO nate_admin USING (true) WITH CHECK (true);
CREATE POLICY gkm_donations_app_own ON gkm_donations
    AS PERMISSIVE FOR ALL TO nate_app
    USING (
        username = COALESCE(current_setting('app.acting_username', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    )
    WITH CHECK (
        username = COALESCE(current_setting('app.acting_username', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    );

-- 16. nate_checkins (user_id column stores usernames, not hardware_ids)
ALTER TABLE nate_checkins ENABLE ROW LEVEL SECURITY;
CREATE POLICY nate_checkins_admin_all ON nate_checkins
    AS PERMISSIVE FOR ALL TO nate_admin USING (true) WITH CHECK (true);
CREATE POLICY nate_checkins_app_own ON nate_checkins
    AS PERMISSIVE FOR ALL TO nate_app
    USING (
        user_id = COALESCE(current_setting('app.acting_username', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    )
    WITH CHECK (
        user_id = COALESCE(current_setting('app.acting_username', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    );

-- 17. checkin_wisdom
ALTER TABLE checkin_wisdom ENABLE ROW LEVEL SECURITY;
CREATE POLICY checkin_wisdom_admin_all ON checkin_wisdom
    AS PERMISSIVE FOR ALL TO nate_admin USING (true) WITH CHECK (true);
CREATE POLICY checkin_wisdom_app_own ON checkin_wisdom
    AS PERMISSIVE FOR ALL TO nate_app
    USING (
        user_id = COALESCE(current_setting('app.acting_username', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    )
    WITH CHECK (
        user_id = COALESCE(current_setting('app.acting_username', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    );

-- 18. token_shares (both sharer and receiver can read; only sharer can write)
ALTER TABLE token_shares ENABLE ROW LEVEL SECURITY;
CREATE POLICY token_shares_admin_all ON token_shares
    AS PERMISSIVE FOR ALL TO nate_admin USING (true) WITH CHECK (true);
CREATE POLICY token_shares_app_own ON token_shares
    AS PERMISSIVE FOR ALL TO nate_app
    USING (
        sharer_username = COALESCE(current_setting('app.acting_username', true), '')
        OR receiver_username = COALESCE(current_setting('app.acting_username', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    )
    WITH CHECK (
        sharer_username = COALESCE(current_setting('app.acting_username', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    );


-- ============================================================
-- GROUP D: Indirect ownership via FK relationships
-- ============================================================

-- 19. session_payment_events (owned via coaching_sessions FK)
ALTER TABLE session_payment_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY session_payment_events_admin_all ON session_payment_events
    AS PERMISSIVE FOR ALL TO nate_admin USING (true) WITH CHECK (true);
CREATE POLICY session_payment_events_app_own ON session_payment_events
    AS PERMISSIVE FOR ALL TO nate_app
    USING (
        session_id IN (
            SELECT id FROM coaching_sessions
            WHERE client_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
               OR coach_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        )
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    )
    WITH CHECK (
        session_id IN (
            SELECT id FROM coaching_sessions
            WHERE client_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
               OR coach_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        )
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    );

-- 20. session_notifications (recipient or session participant)
ALTER TABLE session_notifications ENABLE ROW LEVEL SECURITY;
CREATE POLICY session_notifications_admin_all ON session_notifications
    AS PERMISSIVE FOR ALL TO nate_admin USING (true) WITH CHECK (true);
CREATE POLICY session_notifications_app_own ON session_notifications
    AS PERMISSIVE FOR ALL TO nate_app
    USING (
        recipient_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        OR session_id IN (
            SELECT id FROM coaching_sessions
            WHERE client_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
               OR coach_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        )
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    )
    WITH CHECK (
        recipient_id = COALESCE(current_setting('app.acting_hardware_id', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    );

-- 21. families (visible to members; writable by head of household)
ALTER TABLE families ENABLE ROW LEVEL SECURITY;
CREATE POLICY families_admin_all ON families
    AS PERMISSIVE FOR ALL TO nate_admin USING (true) WITH CHECK (true);
CREATE POLICY families_app_own ON families
    AS PERMISSIVE FOR ALL TO nate_app
    USING (
        id = (
            SELECT family_id FROM users
            WHERE username = COALESCE(current_setting('app.acting_username', true), '')
            LIMIT 1
        )
        OR head_of_household_id = (
            SELECT id FROM users
            WHERE username = COALESCE(current_setting('app.acting_username', true), '')
            LIMIT 1
        )
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    )
    WITH CHECK (
        head_of_household_id = (
            SELECT id FROM users
            WHERE username = COALESCE(current_setting('app.acting_username', true), '')
            LIMIT 1
        )
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    );

COMMIT;

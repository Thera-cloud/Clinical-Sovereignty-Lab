-- Migration 110: Client Nate Messages (check-in follow-up surface)
-- Stores Little Nate's replies to client check-in responses for in-app "Little Nate replied" card.

CREATE TABLE IF NOT EXISTS client_nate_messages (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    message TEXT NOT NULL,
    source VARCHAR(32) NOT NULL DEFAULT 'checkin_followup',
    checkin_wisdom_id UUID REFERENCES checkin_wisdom(id),
    read_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_client_nate_messages_user_read
    ON client_nate_messages (user_id, read_at);
CREATE INDEX IF NOT EXISTS idx_client_nate_messages_created
    ON client_nate_messages (user_id, created_at DESC);

-- RLS: app can read/write own rows; admin all
ALTER TABLE client_nate_messages ENABLE ROW LEVEL SECURITY;
CREATE POLICY client_nate_messages_admin_all ON client_nate_messages
    AS PERMISSIVE FOR ALL TO nate_admin USING (true) WITH CHECK (true);
CREATE POLICY client_nate_messages_app_own ON client_nate_messages
    AS PERMISSIVE FOR ALL TO nate_app
    USING (
        user_id = COALESCE(current_setting('app.acting_username', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    )
    WITH CHECK (
        user_id = COALESCE(current_setting('app.acting_username', true), '')
        OR COALESCE(current_setting('app.acting_role', true), '') = 'ADMIN'
    );

-- Migration 183: Google Calendar two-way sync
-- Tables: google_calendar_connection (per-user OAuth), google_calendar_sync_log (audit)
-- Alters: coaching_sessions (google_event_id, google_etag, sync_state, google_calendar_id,
--                            google_last_synced, sync_source)
--
-- All token columns are Fernet-encrypted at rest via TokenCipher (same as QuickBooks).
-- One row per user (coach OR client). user_id matches users.username for portability with
-- the bridge's PG-first registry; user_role tracks whether the user is COACH or CLIENT.

CREATE TABLE IF NOT EXISTS google_calendar_connection (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR NOT NULL UNIQUE,         -- users.username
    user_role VARCHAR NOT NULL CHECK (user_role IN ('COACH','CLIENT','ADMIN')),
    google_email VARCHAR,
    google_user_id VARCHAR,                  -- Google sub claim
    access_token TEXT NOT NULL,              -- Fernet-encrypted
    refresh_token TEXT NOT NULL,             -- Fernet-encrypted
    token_expiry TIMESTAMPTZ,
    scopes TEXT,                             -- space-separated granted scopes
    target_calendar_id VARCHAR DEFAULT 'primary',
    sync_enabled BOOLEAN DEFAULT true,
    sync_token TEXT,                         -- Google incremental sync token
    last_sync_at TIMESTAMPTZ,
    last_full_sync_at TIMESTAMPTZ,
    error_message TEXT,
    error_count INT DEFAULT 0,
    connected_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_gcal_conn_role ON google_calendar_connection(user_role)
    WHERE sync_enabled = true;
CREATE INDEX IF NOT EXISTS idx_gcal_conn_sync ON google_calendar_connection(last_sync_at)
    WHERE sync_enabled = true;

CREATE TABLE IF NOT EXISTS google_calendar_sync_log (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR NOT NULL,
    direction VARCHAR NOT NULL CHECK (direction IN ('push','pull')),
    action VARCHAR NOT NULL CHECK (action IN ('create','update','delete','noop','error')),
    session_id VARCHAR,                      -- coaching_sessions.session_id
    google_event_id VARCHAR,
    status VARCHAR NOT NULL DEFAULT 'ok',
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_gcal_log_user
    ON google_calendar_sync_log(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_gcal_log_session
    ON google_calendar_sync_log(session_id) WHERE session_id IS NOT NULL;

-- Add sync columns to coaching_sessions (additive only).
-- coaching_sessions.status is VARCHAR(30) free-form (no CHECK constraint) — verified
-- in pre-execution check #3 — so 'cancelled_by_google' may be assigned without ALTER.
ALTER TABLE coaching_sessions ADD COLUMN IF NOT EXISTS google_event_id VARCHAR;
ALTER TABLE coaching_sessions ADD COLUMN IF NOT EXISTS google_etag VARCHAR;
ALTER TABLE coaching_sessions ADD COLUMN IF NOT EXISTS google_calendar_id VARCHAR;
ALTER TABLE coaching_sessions ADD COLUMN IF NOT EXISTS google_last_synced TIMESTAMPTZ;
ALTER TABLE coaching_sessions ADD COLUMN IF NOT EXISTS sync_state VARCHAR DEFAULT 'unsynced';
    -- 'unsynced' | 'pending' | 'synced' | 'error'
ALTER TABLE coaching_sessions ADD COLUMN IF NOT EXISTS sync_source VARCHAR;
    -- 'sanctuary' (created in app) | 'google' (created in Google, mirrored in app)

CREATE INDEX IF NOT EXISTS idx_coaching_sessions_gcal_event
    ON coaching_sessions(google_event_id) WHERE google_event_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_coaching_sessions_sync_state
    ON coaching_sessions(sync_state) WHERE sync_state IN ('pending','error');

-- External busy windows pulled from Google Calendar (NOT Sanctuary sessions).
-- Used by client_get_coach_availability to subtract coach-side conflicts.
-- Cleared/refreshed each pull cycle by GoogleCalendarSyncAgent.
CREATE TABLE IF NOT EXISTS google_external_busy (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR NOT NULL,                -- users.username (coach OR client)
    google_event_id VARCHAR NOT NULL,
    calendar_id VARCHAR NOT NULL DEFAULT 'primary',
    summary VARCHAR,
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, google_event_id)
);
CREATE INDEX IF NOT EXISTS idx_gext_busy_user_window
    ON google_external_busy(user_id, start_at, end_at);

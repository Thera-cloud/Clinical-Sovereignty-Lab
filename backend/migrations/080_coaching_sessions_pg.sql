-- Migration 080: Coaching Sessions PG Table
-- Mirrors the JSON sessions data structure for PG-first reads
-- Replaces sessions.json dependency across all routers

CREATE TABLE IF NOT EXISTS coaching_sessions (
    session_id      VARCHAR(64) PRIMARY KEY,
    client_id       VARCHAR(128) NOT NULL,
    coach_id        VARCHAR(128) NOT NULL,
    family_id       VARCHAR(128) DEFAULT '',
    client_name     VARCHAR(256) DEFAULT '',
    session_type    VARCHAR(32) DEFAULT 'COACH',
    status          VARCHAR(32) DEFAULT 'scheduled',
    scheduled_start TIMESTAMPTZ,
    scheduled_end   TIMESTAMPTZ,
    actual_start    TIMESTAMPTZ,
    actual_end      TIMESTAMPTZ,
    duration_minutes INTEGER DEFAULT 0,
    zoom_link       TEXT DEFAULT '',
    zoom_meeting_id VARCHAR(128) DEFAULT '',
    zoom_host_url   TEXT DEFAULT '',
    notes           TEXT DEFAULT '',
    coach_notes     TEXT DEFAULT '',
    topics_covered  JSONB DEFAULT '[]'::jsonb,
    homework_assigned JSONB DEFAULT '[]'::jsonb,
    mood_at_start   VARCHAR(64) DEFAULT '',
    mood_at_end     VARCHAR(64) DEFAULT '',
    nate_summary    TEXT DEFAULT '',
    recording_url   TEXT DEFAULT '',
    session_data    JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_coaching_sessions_client ON coaching_sessions(client_id);
CREATE INDEX IF NOT EXISTS idx_coaching_sessions_coach ON coaching_sessions(coach_id);
CREATE INDEX IF NOT EXISTS idx_coaching_sessions_status ON coaching_sessions(status);
CREATE INDEX IF NOT EXISTS idx_coaching_sessions_scheduled ON coaching_sessions(scheduled_start);
CREATE INDEX IF NOT EXISTS idx_coaching_sessions_family ON coaching_sessions(family_id) WHERE family_id != '';

CREATE OR REPLACE FUNCTION coaching_sessions_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS coaching_sessions_update_trigger ON coaching_sessions;
CREATE TRIGGER coaching_sessions_update_trigger
    BEFORE UPDATE ON coaching_sessions
    FOR EACH ROW EXECUTE FUNCTION coaching_sessions_updated_at();

-- Migration 063: DOJO Mentor Presence in Zoom Sessions
-- Tracks mentor interactions during live coaching sessions

CREATE TABLE IF NOT EXISTS dojo_mentor_sessions (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL UNIQUE,
    coach_user_id VARCHAR(64) NOT NULL,
    client_user_id VARCHAR(64),
    session_mode VARCHAR(32) NOT NULL DEFAULT 'coach_client',
    active_dojos JSONB NOT NULL DEFAULT '[]',
    zoom_meeting_id VARCHAR(64),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    mentor_interactions_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_dojo_mentor_coach
    ON dojo_mentor_sessions (coach_user_id, started_at DESC);

CREATE TABLE IF NOT EXISTS dojo_mentor_interactions (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL,
    interaction_type VARCHAR(32) NOT NULL,
    content TEXT NOT NULL,
    dojo_lens VARCHAR(32),
    coach_question TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dojo_interactions_session
    ON dojo_mentor_interactions (session_id, created_at);

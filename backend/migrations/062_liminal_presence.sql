-- Migration 062: Liminal Presence Overlay
-- Stores coaching sessions for external conversations (SMS, social, phone calls)

CREATE TABLE IF NOT EXISTS liminal_sessions (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    platform VARCHAR(32) NOT NULL,
    contact_alias VARCHAR(128),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    message_count INTEGER DEFAULT 0,
    call_sid VARCHAR(64),
    call_duration_seconds INTEGER,
    tokens_consumed INTEGER DEFAULT 0,
    call_type VARCHAR(16)
);

CREATE INDEX IF NOT EXISTS idx_liminal_sessions_user
    ON liminal_sessions (user_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_liminal_sessions_platform
    ON liminal_sessions (platform, started_at DESC);

CREATE TABLE IF NOT EXISTS liminal_observations (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES liminal_sessions(id),
    observation_text TEXT NOT NULL,
    coaching_given BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_liminal_obs_session
    ON liminal_observations (session_id);

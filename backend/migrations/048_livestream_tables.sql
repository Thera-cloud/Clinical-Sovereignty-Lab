-- 048: Livestream sessions and wisdom storage
-- Supports Little Nate's multi-platform livestream system

CREATE TABLE IF NOT EXISTS livestream_sessions (
    id              SERIAL PRIMARY KEY,
    session_id      UUID DEFAULT gen_random_uuid() UNIQUE NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending, live, ended, cancelled
    platforms       JSONB NOT NULL DEFAULT '[]',      -- ["x", "youtube", "linkedin"]
    rtmp_keys       JSONB NOT NULL DEFAULT '{}',      -- {"x": "rtmp://...", "youtube": "rtmp://..."}
    topic           TEXT,
    duration_limit  INTEGER NOT NULL DEFAULT 1800,    -- seconds (default 30 min)
    started_at      TIMESTAMPTZ,
    ended_at        TIMESTAMPTZ,
    total_interactions  INTEGER NOT NULL DEFAULT 0,
    unique_viewers      INTEGER NOT NULL DEFAULT 0,
    signups_attributed  INTEGER NOT NULL DEFAULT 0,
    summary         TEXT,                             -- AI-generated session summary
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS livestream_wisdom (
    id              SERIAL PRIMARY KEY,
    session_id      UUID NOT NULL REFERENCES livestream_sessions(session_id),
    platform        TEXT NOT NULL,                    -- x, youtube, linkedin
    viewer_handle   TEXT NOT NULL,                    -- @username or channel name
    viewer_question TEXT NOT NULL,
    nate_response   TEXT NOT NULL,
    emotional_markers JSONB DEFAULT '{}',             -- detected emotions in question
    expression_used TEXT,                             -- avatar expression Nate used
    signup_cta_given BOOLEAN DEFAULT FALSE,
    matched_client_id TEXT,                           -- filled if viewer later signs up
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_livestream_sessions_status ON livestream_sessions(status);
CREATE INDEX idx_livestream_sessions_created ON livestream_sessions(created_at DESC);
CREATE INDEX idx_livestream_wisdom_session ON livestream_wisdom(session_id);
CREATE INDEX idx_livestream_wisdom_viewer ON livestream_wisdom(viewer_handle);
CREATE INDEX idx_livestream_wisdom_matched ON livestream_wisdom(matched_client_id) WHERE matched_client_id IS NOT NULL;

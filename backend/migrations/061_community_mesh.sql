-- Migration 061: Community Mesh — Nate-to-Nate BLE/NFC Group Sessions
-- Supports therapeutic group meetings (AA, SA, etc.) with attendance tracking
-- for probation/court compliance.

CREATE TABLE IF NOT EXISTS community_sessions (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL UNIQUE,
    group_name VARCHAR(128),
    start_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    end_time TIMESTAMPTZ,
    peer_count INTEGER DEFAULT 0,
    topic_tags JSONB DEFAULT '[]',
    momentum_score DOUBLE PRECISION DEFAULT 0.0,
    location_lat DOUBLE PRECISION,
    location_lng DOUBLE PRECISION,
    location_name VARCHAR(256),
    manager_user_id VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS idx_community_sessions_time
    ON community_sessions (start_time DESC);

CREATE TABLE IF NOT EXISTS community_wisdom (
    id SERIAL PRIMARY KEY,
    topic VARCHAR(128) NOT NULL,
    insight_text TEXT NOT NULL,
    convergence_count INTEGER DEFAULT 1,
    source_session_count INTEGER DEFAULT 1,
    location_name VARCHAR(256),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_community_wisdom_topic
    ON community_wisdom (topic, created_at DESC);

CREATE TABLE IF NOT EXISTS community_check_ins (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    check_in_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    check_out_time TIMESTAMPTZ,
    mood_valence DOUBLE PRECISION,
    location_lat DOUBLE PRECISION,
    location_lng DOUBLE PRECISION,
    location_name VARCHAR(256),
    verified BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_check_ins_session
    ON community_check_ins (session_id);
CREATE INDEX IF NOT EXISTS idx_check_ins_user
    ON community_check_ins (user_id, check_in_time DESC);

CREATE TABLE IF NOT EXISTS community_attendance_records (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    display_name VARCHAR(128),
    check_in_time TIMESTAMPTZ NOT NULL,
    check_out_time TIMESTAMPTZ,
    location_name VARCHAR(256),
    group_name VARCHAR(128),
    session_date DATE NOT NULL,
    duration_minutes INTEGER,
    verified_by_manager BOOLEAN DEFAULT FALSE,
    signature_b64 TEXT
);

CREATE INDEX IF NOT EXISTS idx_attendance_user_date
    ON community_attendance_records (user_id, session_date DESC);
CREATE INDEX IF NOT EXISTS idx_attendance_session
    ON community_attendance_records (session_id);

-- Migration 040: Guardian Fibre Foundation (Hive Defense v4.0)
-- Device imprinting, behavioral learning, login protection

-- Guardian Fibre state per user
CREATE TABLE IF NOT EXISTS guardian_fibres (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             TEXT UNIQUE NOT NULL,
    device_imprint_id   TEXT,
    curiosity_state     TEXT NOT NULL DEFAULT 'DORMANT',  -- DORMANT, CURIOUS, SUSPICIOUS, ALARMED, HOSTILE
    anomaly_score       REAL NOT NULL DEFAULT 0.0,
    learning_mode       BOOLEAN DEFAULT TRUE,
    learning_started_at TIMESTAMPTZ,
    learning_ends_at    TIMESTAMPTZ,
    escalation_count    INT DEFAULT 0,
    last_escalation_at  TIMESTAMPTZ,
    sentinel_mode       BOOLEAN DEFAULT FALSE,
    sentinel_until      TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_guardian_fibres_user ON guardian_fibres (user_id);
CREATE INDEX IF NOT EXISTS idx_guardian_fibres_state ON guardian_fibres (curiosity_state);

-- Device imprints (behavioral fingerprints)
CREATE TABLE IF NOT EXISTS device_imprints (
    id                  BIGSERIAL PRIMARY KEY,
    imprint_id          TEXT UNIQUE NOT NULL,
    user_id             TEXT NOT NULL,
    device_type         TEXT,           -- mobile, desktop, tablet
    user_agent_hash     TEXT,
    timezone            TEXT,
    ip_geo_region       TEXT,
    screen_resolution   TEXT,
    language            TEXT,
    typical_login_hours JSONB DEFAULT '[]',
    avg_session_duration_sec INT DEFAULT 0,
    endpoint_patterns   JSONB DEFAULT '{}',
    data_access_patterns JSONB DEFAULT '{}',
    verified            BOOLEAN DEFAULT FALSE,
    last_seen_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_device_imprints_user ON device_imprints (user_id);

-- Guardian state snapshots (24h immutable snapshots for Sentinel Mesh)
CREATE TABLE IF NOT EXISTS guardian_snapshots (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             TEXT NOT NULL,
    snapshot_hash       TEXT NOT NULL,
    curiosity_state     TEXT NOT NULL,
    anomaly_score       REAL NOT NULL,
    behavioral_hash     TEXT,
    signing_key_id      TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_guardian_snapshots_user ON guardian_snapshots (user_id, created_at);

-- Login attempts (brute force protection)
CREATE TABLE IF NOT EXISTS login_attempts (
    id                  BIGSERIAL PRIMARY KEY,
    identifier          TEXT NOT NULL,  -- username, email, or IP
    identifier_type     TEXT NOT NULL,  -- 'username', 'email', 'ip'
    success             BOOLEAN NOT NULL,
    ip_address          TEXT,
    user_agent_hash     TEXT,
    device_imprint_id   TEXT,
    failure_reason      TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_login_attempts_identifier ON login_attempts (identifier, created_at);
CREATE INDEX IF NOT EXISTS idx_login_attempts_created ON login_attempts (created_at);

-- Device verification codes (new device flow)
CREATE TABLE IF NOT EXISTS device_verification_codes (
    id              BIGSERIAL PRIMARY KEY,
    user_id         TEXT NOT NULL,
    device_imprint_id TEXT NOT NULL,
    code_hash       TEXT NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    used            BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_device_verify_user ON device_verification_codes (user_id);

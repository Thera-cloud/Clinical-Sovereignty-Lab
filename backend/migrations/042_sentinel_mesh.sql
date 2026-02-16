-- Migration 042: Sentinel Mesh (Hive Defense v4.2)
-- Guardian-of-Guardians: 8 defenses for monitoring Guardian Fibres

-- Guardian heartbeat log (Defense 2)
CREATE TABLE IF NOT EXISTS guardian_heartbeat_log (
    id              BIGSERIAL PRIMARY KEY,
    user_id         TEXT NOT NULL,
    heartbeat_hash  TEXT NOT NULL,
    signing_key_id  TEXT,
    expected_at     TIMESTAMPTZ,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    latency_ms      INT,
    valid           BOOLEAN DEFAULT TRUE,
    anomaly_type    TEXT  -- late, missing, invalid_signature, duplicate
);
CREATE INDEX IF NOT EXISTS idx_heartbeat_user ON guardian_heartbeat_log (user_id, received_at);

-- Cross-guardian consensus alerts (Defense 3)
CREATE TABLE IF NOT EXISTS cross_guardian_alerts (
    id              BIGSERIAL PRIMARY KEY,
    reporter_id     TEXT NOT NULL,   -- Guardian that detected the issue
    subject_id      TEXT NOT NULL,   -- Guardian being reported on
    alert_type      TEXT NOT NULL,   -- state_mismatch, score_anomaly, snapshot_divergence
    details         JSONB,
    consensus_reached BOOLEAN DEFAULT FALSE,
    consensus_count INT DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cross_guardian_subject ON cross_guardian_alerts (subject_id, created_at);

-- Sentinel mesh state
CREATE TABLE IF NOT EXISTS sentinel_mesh_state (
    id              BIGSERIAL PRIMARY KEY,
    defense_name    TEXT UNIQUE NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active',  -- active, degraded, failed
    last_check_at   TIMESTAMPTZ,
    last_issue_at   TIMESTAMPTZ,
    check_count     BIGINT DEFAULT 0,
    issue_count     BIGINT DEFAULT 0,
    config          JSONB DEFAULT '{}'
);

-- Seed the 8 defenses
INSERT INTO sentinel_mesh_state (defense_name, status) VALUES
    ('imprint_immutability', 'active'),
    ('heartbeat_verification', 'active'),
    ('cross_guardian_consensus', 'active'),
    ('curiosity_ratchet', 'active'),
    ('mirror_authenticity', 'active'),
    ('independent_observer', 'active'),
    ('drift_detection', 'active'),
    ('guardian_diversity', 'active')
ON CONFLICT (defense_name) DO NOTHING;

-- Drift detection baselines (Defense 7)
CREATE TABLE IF NOT EXISTS drift_baselines (
    id              BIGSERIAL PRIMARY KEY,
    user_id         TEXT NOT NULL,
    metric_name     TEXT NOT NULL,
    baseline_value  REAL NOT NULL,
    std_dev         REAL NOT NULL DEFAULT 0,
    sample_count    INT NOT NULL DEFAULT 0,
    window_days     INT NOT NULL DEFAULT 30,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, metric_name)
);
CREATE INDEX IF NOT EXISTS idx_drift_baselines_user ON drift_baselines (user_id);

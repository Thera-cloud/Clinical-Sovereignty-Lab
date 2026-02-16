-- Migration 043: Pipeline Drum (Hive Defense v4.3)
-- Environmental sensing: 4 Tastes (Moisture, Smoke, Burn, Clot) + Resonance Engine

-- Drum baselines (30-day learning)
CREATE TABLE IF NOT EXISTS drum_baselines (
    id              BIGSERIAL PRIMARY KEY,
    sensor_name     TEXT NOT NULL,  -- moisture, smoke, burn, clot
    metric_name     TEXT NOT NULL,
    baseline_mean   REAL NOT NULL DEFAULT 0,
    baseline_std    REAL NOT NULL DEFAULT 1,
    sample_count    INT NOT NULL DEFAULT 0,
    ema_alpha       REAL NOT NULL DEFAULT 0.02,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (sensor_name, metric_name)
);

-- Seed initial baselines
INSERT INTO drum_baselines (sensor_name, metric_name, baseline_mean, baseline_std) VALUES
    ('moisture', 'kl_divergence', 0.0, 1.0),
    ('moisture', 'wasserstein_distance', 0.0, 1.0),
    ('smoke', 'unique_endpoints_per_hour', 10.0, 5.0),
    ('smoke', 'error_rate_per_hour', 0.02, 0.01),
    ('smoke', 'avg_response_time_ms', 200.0, 50.0),
    ('burn', 'avg_entropy', 4.0, 0.5),
    ('burn', 'unusual_encoding_rate', 0.0, 0.01),
    ('clot', 'db_query_rate_per_min', 50.0, 20.0),
    ('clot', 'cache_hit_ratio', 0.8, 0.1),
    ('clot', 'queue_depth', 0.0, 5.0)
ON CONFLICT (sensor_name, metric_name) DO NOTHING;

-- Drum alerts
CREATE TABLE IF NOT EXISTS drum_alerts (
    id              BIGSERIAL PRIMARY KEY,
    sensor_name     TEXT NOT NULL,
    alert_level     INT NOT NULL DEFAULT 1,  -- 1-5 (response levels)
    metric_name     TEXT,
    observed_value  REAL,
    baseline_value  REAL,
    z_score         REAL,
    resonance_multiplier REAL DEFAULT 1.0,
    description     TEXT,
    action_taken    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_drum_alerts_sensor ON drum_alerts (sensor_name, created_at);
CREATE INDEX IF NOT EXISTS idx_drum_alerts_level ON drum_alerts (alert_level, created_at);

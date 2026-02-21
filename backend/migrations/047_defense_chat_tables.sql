-- Migration 047: Defense Chat Tables
-- Creates tables queried by SkyEye Chat defense mode (Big Nate <-> Little Nate)
-- These were referenced in skyeye_chat.py._build_defense_context() but never provisioned

-- Hive Defense service status
CREATE TABLE IF NOT EXISTS hive_defense_status (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    service_name    VARCHAR(255) NOT NULL,
    status          VARCHAR(50) NOT NULL DEFAULT 'unknown',
    details         JSONB DEFAULT '{}',
    checked_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hive_defense_status_checked ON hive_defense_status(checked_at DESC);

-- Hive Defense threat alerts
CREATE TABLE IF NOT EXISTS hive_defense_alerts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_type      VARCHAR(100) NOT NULL,
    severity        VARCHAR(20) NOT NULL DEFAULT 'medium',
    description     TEXT,
    source          VARCHAR(255),
    resolved        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hive_defense_alerts_created ON hive_defense_alerts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_hive_defense_alerts_severity ON hive_defense_alerts(severity);

-- Guardian Fibre events
CREATE TABLE IF NOT EXISTS guardian_fibre_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type      VARCHAR(100) NOT NULL,
    details         JSONB DEFAULT '{}',
    user_id         TEXT,
    fibre_id        UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_guardian_fibre_events_created ON guardian_fibre_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_guardian_fibre_events_type ON guardian_fibre_events(event_type);

-- Seed initial service statuses
INSERT INTO hive_defense_status (service_name, status) VALUES
    ('HiveDefense', 'active'),
    ('GuardianFibre', 'active'),
    ('ContentSentinel', 'active'),
    ('DefconController', 'active'),
    ('CTMonitor', 'active'),
    ('TripwireNetwork', 'active'),
    ('CanaryCredentials', 'active'),
    ('HeartbeatMonitor', 'active'),
    ('CuriosityProtocol', 'active'),
    ('MeshIsolation', 'active')
ON CONFLICT DO NOTHING;

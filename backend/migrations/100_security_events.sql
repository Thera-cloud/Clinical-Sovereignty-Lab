-- Migration 100: Security Events Table
-- Structured security event log for auth failures, anomaly detection, rate limiting

CREATE TABLE IF NOT EXISTS security_events (
    id BIGSERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    severity VARCHAR(10) NOT NULL DEFAULT 'INFO',
    source_ip VARCHAR(45),
    username VARCHAR(255),
    user_agent TEXT,
    endpoint VARCHAR(512),
    detail JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_security_events_type ON security_events (event_type);
CREATE INDEX IF NOT EXISTS idx_security_events_created ON security_events (created_at);
CREATE INDEX IF NOT EXISTS idx_security_events_ip ON security_events (source_ip);
CREATE INDEX IF NOT EXISTS idx_security_events_severity ON security_events (severity) WHERE severity IN ('HIGH', 'CRITICAL');

-- Auto-prune events older than 90 days (handled by db_maintenance_agent)
COMMENT ON TABLE security_events IS 'Structured security audit log — auth failures, anomalies, rate limits. Pruned at 90 days.';

-- Seed with initial entry
INSERT INTO security_events (event_type, severity, detail)
VALUES ('table_created', 'INFO', '{"migration": "100_security_events", "created_by": "security_hardening_mar_2026"}')
ON CONFLICT DO NOTHING;

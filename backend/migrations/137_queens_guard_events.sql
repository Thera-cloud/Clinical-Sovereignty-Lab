-- Migration 137: Queens Guard Events table for Layer 9 Adversarial Resistance
-- Required by: hallucination_defense_architecture_9f29b639.plan.md

CREATE TABLE IF NOT EXISTS queens_guard_events (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(128) NOT NULL,
    event_type VARCHAR(32) NOT NULL,
    severity VARCHAR(16) NOT NULL DEFAULT 'low',
    input_hash VARCHAR(64),
    flags JSONB DEFAULT '[]',
    action_taken VARCHAR(64) NOT NULL DEFAULT 'logged',
    details TEXT,
    source VARCHAR(32) DEFAULT 'bridge',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_qg_events_user ON queens_guard_events(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_qg_events_type ON queens_guard_events(event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_qg_events_severity ON queens_guard_events(severity) WHERE severity IN ('high', 'critical');

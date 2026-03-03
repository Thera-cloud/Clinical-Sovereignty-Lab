-- Migration 069: Liminal Presence Agents
-- Adds table for Silence Sentinel, Language Drift Monitor, and Field Response Parser analysis results.
-- Also adds trust baseline entry for the Liminal Presence Auditor.

CREATE TABLE IF NOT EXISTS liminal_presence_analysis (
    id SERIAL PRIMARY KEY,
    agent TEXT NOT NULL,
    signal TEXT NOT NULL,
    score NUMERIC(4,2),
    detail TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lpa_agent ON liminal_presence_analysis(agent, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_lpa_signal ON liminal_presence_analysis(signal);

INSERT INTO trust_baseline (parameter_key, parameter_value, description, approved_by)
VALUES (
    'liminal_presence_check_count',
    '{"expected": 3, "auditor": "LiminalPresenceAuditor", "activity_type": "liminal_presence_audit_sent"}'::jsonb,
    'Liminal Presence Agents health checks',
    'DrNevedal1'
)
ON CONFLICT (parameter_key) DO NOTHING;

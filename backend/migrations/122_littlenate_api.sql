-- Migration 122: LittleNate-1.X API Tables
-- Creates tables for training pairs, API clients, usage metering, and audit logging.

CREATE TABLE IF NOT EXISTS littlenate_training_pairs (
    id              BIGSERIAL PRIMARY KEY,
    prompt_text     TEXT NOT NULL,
    response_text   TEXT NOT NULL,
    c_knowledge     REAL DEFAULT 0.0,
    c_quantum_self  REAL DEFAULT 0.0,
    felt_sense      VARCHAR(32) DEFAULT 'grounded',
    domain          VARCHAR(64) DEFAULT 'general',
    provider        VARCHAR(32) DEFAULT 'sovereign',
    tokens_used     INTEGER DEFAULT 0,
    latency_ms      INTEGER DEFAULT 0,
    used_for_training BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_training_pairs_score
    ON littlenate_training_pairs ((c_knowledge + c_quantum_self) DESC);
CREATE INDEX IF NOT EXISTS idx_training_pairs_domain
    ON littlenate_training_pairs (domain);
CREATE INDEX IF NOT EXISTS idx_training_pairs_unused
    ON littlenate_training_pairs (used_for_training) WHERE used_for_training = FALSE;

CREATE TABLE IF NOT EXISTS api_clients (
    client_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_secret_hash VARCHAR(128) NOT NULL,
    name            VARCHAR(255) NOT NULL,
    redirect_uri    TEXT,
    tier            VARCHAR(32) DEFAULT 'free' CHECK (tier IN ('free', 'developer', 'enterprise')),
    scopes          JSONB DEFAULT '["nate:chat"]'::jsonb,
    rate_limit      INTEGER DEFAULT 10,
    monthly_cap     INTEGER DEFAULT 1000,
    created_by      VARCHAR(128) NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    is_active       BOOLEAN DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_api_clients_active
    ON api_clients (is_active) WHERE is_active = TRUE;

CREATE TABLE IF NOT EXISTS api_usage (
    id              BIGSERIAL PRIMARY KEY,
    client_id       UUID REFERENCES api_clients(client_id) ON DELETE CASCADE,
    endpoint        VARCHAR(128) NOT NULL,
    tokens_used     INTEGER DEFAULT 0,
    latency_ms      INTEGER DEFAULT 0,
    coherence_score REAL,
    provider        VARCHAR(32),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_usage_client
    ON api_usage (client_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_api_usage_monthly
    ON api_usage (client_id, date_trunc('month', created_at));

CREATE TABLE IF NOT EXISTS api_audit_log (
    id              BIGSERIAL PRIMARY KEY,
    client_id       UUID REFERENCES api_clients(client_id) ON DELETE SET NULL,
    endpoint        VARCHAR(128) NOT NULL,
    method          VARCHAR(10) NOT NULL,
    status_code     INTEGER,
    user_agent      TEXT,
    ip_hash         VARCHAR(64),
    c_knowledge     REAL,
    c_quantum_self  REAL,
    felt_sense      VARCHAR(32),
    latency_ms      INTEGER,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_client
    ON api_audit_log (client_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_date
    ON api_audit_log (created_at DESC);

-- Trust baseline entry for LittleNate API auditor
INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES ('littlenate_api_check_count', '{"expected": 8, "description": "LittleNate-1.X API health, inference, TTS, STT, realtime, coherence, models, OAuth"}')
ON CONFLICT (parameter_key) DO NOTHING;

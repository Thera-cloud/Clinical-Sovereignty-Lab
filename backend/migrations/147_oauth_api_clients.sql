-- Migration 147: OAuth 2.0 API Clients
-- Supports client_credentials grant for machine-to-machine API access

CREATE TABLE IF NOT EXISTS api_clients (
    client_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_secret_hash TEXT NOT NULL,
    name            TEXT NOT NULL,
    redirect_uri    TEXT DEFAULT '',
    tier            TEXT NOT NULL DEFAULT 'free' CHECK (tier IN ('free', 'developer', 'enterprise')),
    scopes          JSONB DEFAULT '["nate:chat"]'::jsonb,
    rate_limit      INT DEFAULT 10,
    monthly_cap     INT DEFAULT 1000,
    is_active       BOOLEAN DEFAULT TRUE,
    created_by      TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_clients_active ON api_clients (is_active) WHERE is_active = TRUE;

CREATE TABLE IF NOT EXISTS api_usage (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       UUID REFERENCES api_clients(client_id),
    endpoint        TEXT,
    method          TEXT,
    status_code     INT,
    latency_ms      INT,
    tokens_used     INT DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_usage_client ON api_usage (client_id, created_at);
CREATE INDEX IF NOT EXISTS idx_api_usage_monthly ON api_usage (client_id, created_at)
    WHERE created_at >= date_trunc('month', NOW());

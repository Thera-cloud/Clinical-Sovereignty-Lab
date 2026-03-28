-- OAuth provider: client registry for third-party app integrations
-- Migration 128

CREATE TABLE IF NOT EXISTS oauth_clients (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    client_id VARCHAR(64) UNIQUE NOT NULL,
    client_secret_hash VARCHAR(128) NOT NULL,
    app_name VARCHAR(255) NOT NULL,
    redirect_uris JSONB DEFAULT '[]'::jsonb,
    scopes JSONB DEFAULT '[]'::jsonb,
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oauth_clients_client_id ON oauth_clients(client_id);
CREATE INDEX IF NOT EXISTS idx_oauth_clients_active ON oauth_clients(active) WHERE active = true;

-- Migration 132: Enterprise API Keys
-- Supports 4-tier API access (FREE/STARTER/GROWTH/ENTERPRISE)
-- Keys validated at Edge via D1 sync for sub-ms auth

CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_name TEXT NOT NULL,
    api_key TEXT UNIQUE NOT NULL,
    tier TEXT NOT NULL DEFAULT 'FREE' CHECK (tier IN ('FREE', 'STARTER', 'GROWTH', 'ENTERPRISE')),
    contact_email TEXT DEFAULT '',
    rate_limit_per_minute INT DEFAULT 60,
    daily_limit INT DEFAULT 1000,
    monthly_usage INT DEFAULT 0,
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_keys_active ON api_keys (active) WHERE active = true;
CREATE INDEX IF NOT EXISTS idx_api_keys_org ON api_keys (org_name);

-- L2 face table for ODPE 24M-face self-population
CREATE TABLE IF NOT EXISTS odpe_l2_faces (
    face_path TEXT PRIMARY KEY,
    activation_count INT DEFAULT 1,
    last_activated TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_odpe_l2_faces_activation ON odpe_l2_faces (activation_count DESC);
CREATE INDEX IF NOT EXISTS idx_odpe_l2_faces_last ON odpe_l2_faces (last_activated DESC);

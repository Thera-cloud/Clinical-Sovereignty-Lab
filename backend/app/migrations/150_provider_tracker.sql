-- 150_provider_tracker.sql
-- Provider usage tracking for inference cost analysis

CREATE TABLE IF NOT EXISTS provider_usage (
    id BIGSERIAL PRIMARY KEY,
    family_id UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider_name VARCHAR(50) NOT NULL, -- 'openai', 'anthropic', 'azure', etc.
    model_name VARCHAR(100) NOT NULL,
    tokens_prompt INTEGER NOT NULL DEFAULT 0,
    tokens_completion INTEGER NOT NULL DEFAULT 0,
    cost_usd NUMERIC(10,6) NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    success BOOLEAN NOT NULL DEFAULT true,
    session_id UUID REFERENCES sessions(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    INDEX idx_provider_usage_family (family_id, created_at),
    INDEX idx_provider_usage_user (user_id, provider_name, created_at)
);

CREATE TABLE IF NOT EXISTS provider_stats_daily (
    id BIGSERIAL PRIMARY KEY,
    date DATE NOT NULL,
    provider_name VARCHAR(50) NOT NULL,
    total_calls INTEGER NOT NULL DEFAULT 0,
    total_prompt_tokens BIGINT NOT NULL DEFAULT 0,
    total_completion_tokens BIGINT NOT NULL DEFAULT 0,
    total_cost NUMERIC(12,6) NOT NULL DEFAULT 0,
    avg_latency_ms INTEGER NOT NULL DEFAULT 0,
    success_rate NUMERIC(5,4) NOT NULL DEFAULT 1.0,
    UNIQUE(provider_name, date)
);

COMMENT ON TABLE provider_usage IS 'Granular tracking of inference provider calls per user/session';
COMMENT ON TABLE provider_stats_daily IS 'Aggregated daily stats for billing + capacity planning';

CREATE TABLE IF NOT EXISTS provider_stats (
    id BIGSERIAL PRIMARY KEY,
    family_id UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
    provider_name VARCHAR(50) NOT NULL,
    total_calls INTEGER NOT NULL DEFAULT 0,
    total_prompt_tokens BIGINT NOT NULL DEFAULT 0,
    total_completion_tokens BIGINT NOT NULL DEFAULT 0,
    total_cost NUMERIC(12,6) NOT NULL DEFAULT 0,
    avg_latency_ms INTEGER NOT NULL DEFAULT 0,
    success_rate NUMERIC(5,4) NOT NULL DEFAULT 1.0,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(family_id, provider_name),
    INDEX idx_provider_stats_family (family_id, total_cost DESC)
);

COMMENT ON TABLE provider_stats IS 'Family-level lifetime provider usage aggregates for dashboards';
-- Migration 133: Monetization Control Credit Ledger + Dual-Rail Reconciliation
-- Introduces append-only usage/rating tables and entitlement reconciliation primitives.

-- 1) Unified usage event stream
CREATE TABLE IF NOT EXISTS usage_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor_type VARCHAR(40) NOT NULL DEFAULT 'user',
    actor_id TEXT NOT NULL,
    tenant_id TEXT,
    channel VARCHAR(60) NOT NULL DEFAULT 'unknown',
    feature_key VARCHAR(120) NOT NULL,
    depth_class VARCHAR(40) NOT NULL DEFAULT 'core' CHECK (depth_class IN ('core', 'deep_noetic')),
    quantity NUMERIC(18,6) NOT NULL DEFAULT 1,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_usage_events_occurred_at
    ON usage_events(occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_events_tenant_time
    ON usage_events(tenant_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_events_depth
    ON usage_events(depth_class, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_events_channel
    ON usage_events(channel, occurred_at DESC);

-- 2) Rule-versioned ratings for margin controls
CREATE TABLE IF NOT EXISTS usage_ratings (
    rating_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES usage_events(event_id) ON DELETE CASCADE,
    rule_version VARCHAR(60) NOT NULL DEFAULT 'v1',
    credits_burned NUMERIC(18,6) NOT NULL DEFAULT 0,
    cost_estimate_cents BIGINT NOT NULL DEFAULT 0,
    margin_band VARCHAR(20) NOT NULL DEFAULT 'unknown',
    rated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_usage_ratings_event
    ON usage_ratings(event_id);
CREATE INDEX IF NOT EXISTS idx_usage_ratings_rated_at
    ON usage_ratings(rated_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_ratings_margin_band
    ON usage_ratings(margin_band, rated_at DESC);

-- 3) Wallet snapshots per billing period
CREATE TABLE IF NOT EXISTS credit_wallets (
    wallet_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_type VARCHAR(40) NOT NULL DEFAULT 'user',
    owner_id TEXT NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    included_credits NUMERIC(18,6) NOT NULL DEFAULT 0,
    consumed_credits NUMERIC(18,6) NOT NULL DEFAULT 0,
    remaining_credits NUMERIC(18,6) NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (owner_type, owner_id, period_start, period_end)
);

CREATE INDEX IF NOT EXISTS idx_credit_wallets_owner_period
    ON credit_wallets(owner_type, owner_id, period_start DESC);

-- 4) Pricing rule versions for governed rollout
CREATE TABLE IF NOT EXISTS pricing_rule_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_version VARCHAR(60) NOT NULL UNIQUE,
    status VARCHAR(30) NOT NULL DEFAULT 'draft',
    rules_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    effective_at TIMESTAMPTZ,
    created_by TEXT DEFAULT 'system',
    approved_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_pricing_rule_versions_status
    ON pricing_rule_versions(status, created_at DESC);

-- 5) Entitlement snapshots for Stripe + Apple dual-rail
CREATE TABLE IF NOT EXISTS entitlement_snapshots (
    snapshot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id TEXT NOT NULL,
    source_rail VARCHAR(20) NOT NULL CHECK (source_rail IN ('stripe', 'apple', 'manual')),
    source_ref TEXT NOT NULL DEFAULT '',
    entitlement_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    effective_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    effective_to TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_entitlement_snapshots_account
    ON entitlement_snapshots(account_id, effective_from DESC);
CREATE INDEX IF NOT EXISTS idx_entitlement_snapshots_active
    ON entitlement_snapshots(is_active, source_rail, effective_from DESC);

-- 6) Reconciliation conflict queue (read-only reconcile then manual resolve)
CREATE TABLE IF NOT EXISTS entitlement_reconciliation_conflicts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id TEXT NOT NULL,
    stripe_state VARCHAR(30) NOT NULL DEFAULT 'none',
    apple_state VARCHAR(30) NOT NULL DEFAULT 'none',
    effective_state VARCHAR(30) NOT NULL DEFAULT 'none',
    reason TEXT NOT NULL DEFAULT 'unknown',
    status VARCHAR(30) NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    resolved_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_entitlement_conflicts_status
    ON entitlement_reconciliation_conflicts(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_entitlement_conflicts_account
    ON entitlement_reconciliation_conflicts(account_id, created_at DESC);

-- 7) Governed pricing proposals (propose -> approve -> apply)
CREATE TABLE IF NOT EXISTS pricing_change_proposals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    proposal_type VARCHAR(50) NOT NULL DEFAULT 'pricing_rules',
    title TEXT NOT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(30) NOT NULL DEFAULT 'proposed',
    proposed_by TEXT NOT NULL DEFAULT 'system',
    approved_by TEXT,
    applied_by TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_at TIMESTAMPTZ,
    applied_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_pricing_proposals_status
    ON pricing_change_proposals(status, created_at DESC);

-- 7) Seed baseline pricing rule version
INSERT INTO pricing_rule_versions (rule_version, status, rules_json, created_by)
VALUES (
    'v1',
    'active',
    '{"depth_class":{"core":{"credit_per_unit":1},"deep_noetic":{"credit_per_unit":4}}}'::jsonb,
    'migration_133'
)
ON CONFLICT (rule_version) DO NOTHING;

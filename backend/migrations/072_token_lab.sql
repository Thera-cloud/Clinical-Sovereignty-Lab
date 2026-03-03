-- Token Lab: Token management, transaction history, and cost tracking
-- Migration 072

CREATE TABLE IF NOT EXISTS token_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(100) NOT NULL,
    action VARCHAR(50) NOT NULL,  -- 'adjust', 'reward', 'mass_drop', 'deduct', 'purchase', 'reset'
    amount INTEGER NOT NULL,       -- positive = added, negative = deducted
    balance_before INTEGER NOT NULL,
    balance_after INTEGER NOT NULL,
    reason TEXT,
    batch_id UUID,                 -- groups mass operations together
    initiated_by VARCHAR(100) NOT NULL DEFAULT 'system',
    target_scope VARCHAR(50),      -- 'individual', 'family', 'group', 'network', 'selected'
    target_ref VARCHAR(200),       -- family_id, company_id, or comma-separated usernames
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_token_tx_username ON token_transactions(username);
CREATE INDEX IF NOT EXISTS idx_token_tx_action ON token_transactions(action);
CREATE INDEX IF NOT EXISTS idx_token_tx_batch ON token_transactions(batch_id);
CREATE INDEX IF NOT EXISTS idx_token_tx_created ON token_transactions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_token_tx_scope ON token_transactions(target_scope);

CREATE TABLE IF NOT EXISTS token_cost_config (
    id SERIAL PRIMARY KEY,
    cost_per_token NUMERIC(10, 6) NOT NULL DEFAULT 0.0001,
    price_per_token NUMERIC(10, 6) NOT NULL DEFAULT 0.001,
    effective_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes TEXT,
    created_by VARCHAR(100) NOT NULL DEFAULT 'DrNevedal1'
);

INSERT INTO token_cost_config (cost_per_token, price_per_token, notes)
VALUES (0.0001, 0.001, 'Initial token economics: $0.0001 cost, $0.001 price per token')
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS token_usage_snapshots (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL,
    snapshot_date DATE NOT NULL DEFAULT CURRENT_DATE,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    tokens_added INTEGER NOT NULL DEFAULT 0,
    balance_at_snapshot INTEGER NOT NULL DEFAULT 0,
    source VARCHAR(50),  -- 'session', 'voice_call', 'ai_chat', 'family_sanctuary', etc.
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_token_snap_user_date_src
    ON token_usage_snapshots(username, snapshot_date, COALESCE(source, ''));
CREATE INDEX IF NOT EXISTS idx_token_snap_date ON token_usage_snapshots(snapshot_date DESC);

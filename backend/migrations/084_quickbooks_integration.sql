-- Migration 084: QuickBooks Online integration tables
-- Enables full custom QB sync for subscriptions, token purchases,
-- GKM donations, coach payouts, and corporate invoicing.

-- QB OAuth connection (single-row, one company connection at a time)
CREATE TABLE IF NOT EXISTS qb_connection (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    realm_id        VARCHAR(50) NOT NULL,
    access_token    TEXT NOT NULL,
    refresh_token   TEXT NOT NULL,
    token_expiry    TIMESTAMPTZ NOT NULL,
    company_name    VARCHAR(200),
    connected_by    VARCHAR(100) NOT NULL,
    connected_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_sync_at    TIMESTAMPTZ,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Sync audit log
CREATE TABLE IF NOT EXISTS qb_sync_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sync_type       VARCHAR(40) NOT NULL CHECK (sync_type IN (
                        'subscription','token_purchase','gkm_donation',
                        'coach_payout','corporate_invoice')),
    source_table    VARCHAR(60) NOT NULL,
    source_id       UUID NOT NULL,
    qb_entity_type  VARCHAR(30) NOT NULL,
    qb_entity_id    VARCHAR(60),
    amount_cents    INTEGER NOT NULL DEFAULT 0,
    status          VARCHAR(20) NOT NULL DEFAULT 'synced' CHECK (status IN ('synced','failed','skipped')),
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_qb_sync_log_type ON qb_sync_log(sync_type);
CREATE INDEX IF NOT EXISTS idx_qb_sync_log_created ON qb_sync_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_qb_sync_log_status ON qb_sync_log(status);

-- Account mapping (internal category → QB Chart of Accounts)
CREATE TABLE IF NOT EXISTS qb_account_mapping (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    internal_category   VARCHAR(40) NOT NULL UNIQUE CHECK (internal_category IN (
                            'subscription_revenue','token_sales','gkm_donations',
                            'coach_payouts','corporate_revenue')),
    qb_account_id       VARCHAR(60) NOT NULL,
    qb_account_name     VARCHAR(200),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Add synced_to_qb tracking columns on financial tables
ALTER TABLE payment_history ADD COLUMN IF NOT EXISTS synced_to_qb BOOLEAN DEFAULT FALSE;
ALTER TABLE token_transactions ADD COLUMN IF NOT EXISTS synced_to_qb BOOLEAN DEFAULT FALSE;
ALTER TABLE gkm_donations ADD COLUMN IF NOT EXISTS synced_to_qb BOOLEAN DEFAULT FALSE;
ALTER TABLE signup_sharing_ledger ADD COLUMN IF NOT EXISTS synced_to_qb BOOLEAN DEFAULT FALSE;

-- Indexes for efficient "unsynced" queries
CREATE INDEX IF NOT EXISTS idx_payment_history_qb ON payment_history(synced_to_qb) WHERE synced_to_qb = FALSE;
CREATE INDEX IF NOT EXISTS idx_token_tx_qb ON token_transactions(synced_to_qb) WHERE synced_to_qb = FALSE;
CREATE INDEX IF NOT EXISTS idx_gkm_donations_qb ON gkm_donations(synced_to_qb) WHERE synced_to_qb = FALSE;
CREATE INDEX IF NOT EXISTS idx_sharing_ledger_qb ON signup_sharing_ledger(synced_to_qb) WHERE synced_to_qb = FALSE;

-- Trust baseline entries for new auditors
INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES ('quickbooks_check_count', '{"expected": 10}'::jsonb)
ON CONFLICT (parameter_key) DO UPDATE SET parameter_value = EXCLUDED.parameter_value;

INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES ('corporate_command_check_count', '{"expected": 12}'::jsonb)
ON CONFLICT (parameter_key) DO UPDATE SET parameter_value = EXCLUDED.parameter_value;

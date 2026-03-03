-- Migration 076: Token Usage Agent, Token Sharing, GKM Donations
-- Adds source tracking to token_transactions, creates token sharing
-- and GKM donation tables for the Greatest in the Kingdom 501(c)(3) integration.

-- 1. Add source column to token_transactions for per-feature tracking
ALTER TABLE token_transactions
    ADD COLUMN IF NOT EXISTS source VARCHAR(50);

CREATE INDEX IF NOT EXISTS idx_token_tx_source
    ON token_transactions(source) WHERE source IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_token_tx_username_source
    ON token_transactions(username, source, created_at DESC);

-- 2. Add index for snapshot queries
CREATE INDEX IF NOT EXISTS idx_token_snapshots_user_date
    ON token_usage_snapshots(username, snapshot_date, source);

-- 3. Token Shares — BLE/NFC peer-to-peer token transfers
CREATE TABLE IF NOT EXISTS token_shares (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sharer_username VARCHAR(100) NOT NULL,
    receiver_username VARCHAR(100) NOT NULL,
    tokens_shared INTEGER NOT NULL CHECK (tokens_shared > 0),
    share_fee_cents INTEGER NOT NULL CHECK (share_fee_cents >= 0),
    stripe_payment_id VARCHAR(200),
    donation_eligible BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_token_shares_sharer
    ON token_shares(sharer_username, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_token_shares_receiver
    ON token_shares(receiver_username, created_at DESC);

-- 4. GKM Donations — Greatest in the Kingdom Ministry donation ledger
CREATE TABLE IF NOT EXISTS gkm_donations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username VARCHAR(100) NOT NULL,
    donation_amount_cents INTEGER NOT NULL CHECK (donation_amount_cents > 0),
    source VARCHAR(50) DEFAULT 'token_share',
    cumulative_total_cents INTEGER NOT NULL DEFAULT 0,
    receipt_sent BOOLEAN DEFAULT FALSE,
    receipt_sent_at TIMESTAMPTZ,
    tax_year INTEGER NOT NULL,
    stripe_payment_id VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gkm_donations_user_year
    ON gkm_donations(username, tax_year, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_gkm_donations_threshold
    ON gkm_donations(tax_year, cumulative_total_cents DESC);

-- 5. GKM Annual Receipts — year-end donation receipt tracking
CREATE TABLE IF NOT EXISTS gkm_annual_receipts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username VARCHAR(100) NOT NULL,
    tax_year INTEGER NOT NULL,
    total_donations_cents INTEGER NOT NULL DEFAULT 0,
    receipt_pdf_path TEXT,
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (username, tax_year)
);

-- 6. GKM Discounts — promotional discount tracking
CREATE TABLE IF NOT EXISTS gkm_discounts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username VARCHAR(100),
    discount_type VARCHAR(50) NOT NULL,
    discount_code VARCHAR(100),
    amount_cents INTEGER NOT NULL DEFAULT 0,
    description TEXT,
    applied_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gkm_discounts_user
    ON gkm_discounts(username, applied_at DESC);

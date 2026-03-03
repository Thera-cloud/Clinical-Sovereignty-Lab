-- Migration 086: Multi-Tenant QuickBooks (Corp + Coach)
-- Adds company-scoped and coach-scoped QB connection, sync log, and account mapping tables.
-- Adds tracking columns to payment_history, token_transactions, and signup_sharing_ledger.
-- Updates trust_baseline expected counts for auditors that gain QB endpoints.

BEGIN;

-- ═══════════════════════════════════════════════════════════════════════════
-- Corp QB Tables
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS qb_corp_connection (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL REFERENCES corporate_sponsors(id),
    realm_id        VARCHAR(50) NOT NULL,
    access_token    TEXT,
    refresh_token   TEXT,
    token_expiry    TIMESTAMPTZ,
    company_name    VARCHAR(200),
    connected_by    VARCHAR(100),
    connected_at    TIMESTAMPTZ DEFAULT NOW(),
    last_sync_at    TIMESTAMPTZ,
    error_message   TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_qb_corp_company UNIQUE (company_id)
);

CREATE TABLE IF NOT EXISTS qb_corp_sync_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL REFERENCES corporate_sponsors(id),
    sync_type       VARCHAR(50) NOT NULL,
    source_table    VARCHAR(100),
    source_id       UUID,
    qb_entity_type  VARCHAR(50),
    qb_entity_id    VARCHAR(100),
    amount_cents    INTEGER DEFAULT 0,
    status          VARCHAR(20) DEFAULT 'synced',
    error_message   TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS qb_corp_account_mapping (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id          UUID NOT NULL REFERENCES corporate_sponsors(id),
    internal_category   VARCHAR(50) NOT NULL,
    qb_account_id       VARCHAR(100) NOT NULL,
    qb_account_name     VARCHAR(200) DEFAULT '',
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_qb_corp_mapping UNIQUE (company_id, internal_category),
    CONSTRAINT chk_corp_category CHECK (internal_category IN (
        'employee_subscriptions', 'employee_tokens', 'corporate_billing'
    ))
);

CREATE INDEX IF NOT EXISTS idx_qb_corp_sync_log_company
    ON qb_corp_sync_log (company_id, created_at DESC);

-- ═══════════════════════════════════════════════════════════════════════════
-- Coach QB Tables
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS qb_coach_connection (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coach_username  VARCHAR(100) NOT NULL,
    realm_id        VARCHAR(50) NOT NULL,
    access_token    TEXT,
    refresh_token   TEXT,
    token_expiry    TIMESTAMPTZ,
    company_name    VARCHAR(200),
    connected_by    VARCHAR(100),
    connected_at    TIMESTAMPTZ DEFAULT NOW(),
    last_sync_at    TIMESTAMPTZ,
    error_message   TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_qb_coach_username UNIQUE (coach_username)
);

CREATE TABLE IF NOT EXISTS qb_coach_sync_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coach_username  VARCHAR(100) NOT NULL,
    sync_type       VARCHAR(50) NOT NULL,
    source_table    VARCHAR(100),
    source_id       UUID,
    qb_entity_type  VARCHAR(50),
    qb_entity_id    VARCHAR(100),
    amount_cents    INTEGER DEFAULT 0,
    status          VARCHAR(20) DEFAULT 'synced',
    error_message   TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS qb_coach_account_mapping (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coach_username      VARCHAR(100) NOT NULL,
    internal_category   VARCHAR(50) NOT NULL,
    qb_account_id       VARCHAR(100) NOT NULL,
    qb_account_name     VARCHAR(200) DEFAULT '',
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_qb_coach_mapping UNIQUE (coach_username, internal_category),
    CONSTRAINT chk_coach_category CHECK (internal_category IN (
        'coaching_revenue', 'session_income'
    ))
);

CREATE INDEX IF NOT EXISTS idx_qb_coach_sync_log_username
    ON qb_coach_sync_log (coach_username, created_at DESC);

-- ═══════════════════════════════════════════════════════════════════════════
-- Tracking Columns
-- ═══════════════════════════════════════════════════════════════════════════

ALTER TABLE payment_history
    ADD COLUMN IF NOT EXISTS synced_to_corp_qb BOOLEAN DEFAULT FALSE;

ALTER TABLE token_transactions
    ADD COLUMN IF NOT EXISTS synced_to_corp_qb BOOLEAN DEFAULT FALSE;

ALTER TABLE signup_sharing_ledger
    ADD COLUMN IF NOT EXISTS synced_to_coach_qb BOOLEAN DEFAULT FALSE;

-- ═══════════════════════════════════════════════════════════════════════════
-- Trust Baseline Updates
-- Corp auditor: 12 -> 21 (+9 QB endpoints)
-- Coach DOJO auditor: 46 -> 55 (+9 QB endpoints)
-- ═══════════════════════════════════════════════════════════════════════════

UPDATE trust_baseline
SET parameter_value = jsonb_set(parameter_value, '{expected}', '21')
WHERE parameter_key = 'corporate_command_check_count';

UPDATE trust_baseline
SET parameter_value = jsonb_set(parameter_value, '{expected}', '55')
WHERE parameter_key = 'coach_dojo_endpoint_count';

COMMIT;

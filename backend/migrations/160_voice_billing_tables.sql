-- Migration 160: Voice Therapy Prepaid Billing Tables
-- SOVEREIGN-VOICE

-- Per-client prepaid balance ledger
-- user_id stores UUID string from users.id::text when available,
-- or phone number as temporary identifier for unregistered callers (Gap C).
CREATE TABLE IF NOT EXISTS voice_accounts (
    user_id         TEXT PRIMARY KEY,
    phone           TEXT NOT NULL,
    balance_seconds INTEGER NOT NULL DEFAULT 0,
    stripe_customer_id TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_voice_accounts_phone
    ON voice_accounts(phone);

-- Per-call session log with PAUSED state support
CREATE TABLE IF NOT EXISTS voice_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         TEXT NOT NULL REFERENCES voice_accounts(user_id),
    call_sid        TEXT,
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'completed', 'paused', 'expired')),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at        TIMESTAMPTZ,
    paused_at       TIMESTAMPTZ,
    seconds_used    INTEGER NOT NULL DEFAULT 0,
    end_reason      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_voice_sessions_user_status
    ON voice_sessions(user_id, status);

-- Ledger of all balance changes (purchases, deductions, extensions)
CREATE TABLE IF NOT EXISTS voice_transactions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         TEXT NOT NULL REFERENCES voice_accounts(user_id),
    session_id      UUID REFERENCES voice_sessions(id),
    type            TEXT NOT NULL CHECK (type IN ('purchase', 'deduction', 'extension', 'refund', 'admin_grant')),
    seconds         INTEGER NOT NULL,
    amount_cents    INTEGER DEFAULT 0,
    stripe_payment_id TEXT,
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_voice_transactions_user
    ON voice_transactions(user_id, created_at DESC);

-- Post-session memory crystals for contextual check-ins
CREATE TABLE IF NOT EXISTS voice_crystals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         TEXT NOT NULL,
    session_id      UUID REFERENCES voice_sessions(id),
    summary         TEXT,
    topics          TEXT,
    emotional_state TEXT,
    therapeutic_notes TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_voice_crystals_user
    ON voice_crystals(user_id, created_at DESC);

-- Lead capture for unknown callers who don't yet have a platform account
CREATE TABLE IF NOT EXISTS voice_leads (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone           TEXT NOT NULL,
    call_count      INTEGER NOT NULL DEFAULT 1,
    last_call_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sms_sent        BOOLEAN NOT NULL DEFAULT FALSE,
    converted       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_voice_leads_phone
    ON voice_leads(phone);

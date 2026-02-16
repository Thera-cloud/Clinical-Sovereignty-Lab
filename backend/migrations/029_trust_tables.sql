-- Migration 029: Trust Framework + Night School Indexes + Vault Billing

-- =============================================================================
-- NIGHT SCHOOL INGESTION TRACKING
-- =============================================================================

CREATE TABLE IF NOT EXISTS night_school_ingestions (
    content_hash    TEXT PRIMARY KEY,
    source          TEXT,
    content_type    TEXT,
    status          TEXT DEFAULT 'pending',
    metadata        JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS night_school_indexes (
    index_id        TEXT PRIMARY KEY,
    source          TEXT,
    chunks_indexed  INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS night_school_queue (
    id              SERIAL PRIMARY KEY,
    source_name     TEXT NOT NULL,
    content_type    TEXT NOT NULL,
    raw_content     TEXT NOT NULL,
    metadata        JSONB DEFAULT '{}'::jsonb,
    status          TEXT DEFAULT 'pending',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_night_school_queue_status ON night_school_queue(status);

-- =============================================================================
-- LEGACY VAULT BILLING
-- =============================================================================

CREATE TABLE IF NOT EXISTS legacy_vault_billing (
    user_id         TEXT PRIMARY KEY,
    vault_size_gb   FLOAT DEFAULT 0,
    tier            TEXT DEFAULT 'standard',
    monthly_cost    FLOAT DEFAULT 0,
    last_billed     TIMESTAMPTZ,
    retention_years INTEGER DEFAULT 100,
    stripe_price_id TEXT,
    CONSTRAINT fk_vault_billing_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- =============================================================================
-- SESSION SUMMARIES (for briefing generator)
-- =============================================================================

CREATE TABLE IF NOT EXISTS session_summaries (
    id              SERIAL PRIMARY KEY,
    session_id      TEXT,
    client_id       TEXT NOT NULL,
    themes          JSONB DEFAULT '[]'::jsonb,
    unresolved_topics JSONB DEFAULT '[]'::jsonb,
    homework_status TEXT DEFAULT 'unknown',
    summary_text    TEXT DEFAULT '',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_session_summaries_client ON session_summaries(client_id);

-- =============================================================================
-- FAMILY MEMBERS (for SLF export)
-- =============================================================================

CREATE TABLE IF NOT EXISTS family_members (
    id              SERIAL PRIMARY KEY,
    family_id       TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    role            TEXT DEFAULT 'member',
    joined_at       TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT fk_family_member_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_family_members_family ON family_members(family_id);
CREATE INDEX IF NOT EXISTS idx_family_members_user ON family_members(user_id);

-- =============================================================================
-- GUARDIAN SUCCESSION CHECK LOGS
-- =============================================================================

CREATE TABLE IF NOT EXISTS guardian_succession_checks (
    id              SERIAL PRIMARY KEY,
    trust_id        TEXT NOT NULL,
    checked_at      TIMESTAMPTZ DEFAULT NOW(),
    primary_guardian_active BOOLEAN DEFAULT TRUE,
    successor_notified BOOLEAN DEFAULT FALSE
);

-- =============================================================================
-- ADDITIONAL INDEXES FOR PERFORMANCE
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_me2me_imprints_captured ON me2me_imprint_entries(captured_at);
CREATE INDEX IF NOT EXISTS idx_me2me_crystals_version ON me2me_identity_crystals(user_id, crystal_version);
CREATE INDEX IF NOT EXISTS idx_me2me_avatars_active ON me2me_avatars(status) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_visitor_sessions_active ON me2me_visitor_sessions(ended_at) WHERE ended_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_consent_renewal ON me2me_consent_records(renewal_due) WHERE status = 'active';

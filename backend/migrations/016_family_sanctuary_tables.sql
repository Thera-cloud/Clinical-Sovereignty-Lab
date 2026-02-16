-- =============================================================================
-- Migration 016: Family Sanctuary PostgreSQL Tables
-- DDL definitions for Family Sanctuary data that is currently stored in JSON.
-- These tables enable future migration from family_sanctuaries.json to
-- PostgreSQL for better querying, concurrency, and data integrity.
-- =============================================================================

-- ─── Family Sanctuary Sessions ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS family_sanctuary_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_id       UUID REFERENCES families(id) ON DELETE SET NULL,
    session_type    VARCHAR(32) NOT NULL DEFAULT 'family',   -- family | couples | mediation
    status          VARCHAR(32) NOT NULL DEFAULT 'pending',  -- pending | onboarding | active | paused | completed | cancelled
    modality        VARCHAR(64),                              -- family_systems | eft | ifs | legacy_healing
    base_fee_cents  INTEGER NOT NULL DEFAULT 2000,
    total_cost_cents INTEGER NOT NULL DEFAULT 0,
    invitation_code VARCHAR(64) UNIQUE,
    c_emo_family    FLOAT,                                    -- aggregate family coherence
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sanc_session_family ON family_sanctuary_sessions(family_id);
CREATE INDEX IF NOT EXISTS idx_sanc_session_status ON family_sanctuary_sessions(status);


-- ─── Sanctuary Members ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sanctuary_members (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES family_sanctuary_sessions(id) ON DELETE CASCADE,
    user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
    display_name    VARCHAR(128) NOT NULL,
    role            VARCHAR(32) NOT NULL DEFAULT 'member',   -- creator | member | observer | minor
    consent_agreed  BOOLEAN DEFAULT FALSE,
    terms_acknowledged BOOLEAN DEFAULT FALSE,
    joined_at       TIMESTAMPTZ,
    exited_at       TIMESTAMPTZ,
    status          VARCHAR(16) NOT NULL DEFAULT 'invited',  -- invited | onboarding | active | exited
    metadata        JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_sanc_member_session ON sanctuary_members(session_id);
CREATE INDEX IF NOT EXISTS idx_sanc_member_user    ON sanctuary_members(user_id);


-- ─── Sanctuary Messages ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sanctuary_messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES family_sanctuary_sessions(id) ON DELETE CASCADE,
    sender_id       UUID REFERENCES users(id) ON DELETE SET NULL,
    sender_name     VARCHAR(128),
    sender_type     VARCHAR(16) NOT NULL DEFAULT 'member',   -- member | ai | coach | system
    content         TEXT NOT NULL,
    message_type    VARCHAR(32) DEFAULT 'message',           -- message | coaching | intervention | summary
    metadata        JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sanc_msg_session ON sanctuary_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_sanc_msg_time    ON sanctuary_messages(created_at);


-- ─── Sanctuary Interventions ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sanctuary_interventions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES family_sanctuary_sessions(id) ON DELETE CASCADE,
    intervention_type VARCHAR(32) NOT NULL,        -- escalation | coaching_offer | cool_down | ai_redirect
    trigger_reason  TEXT,
    trigger_message_id UUID REFERENCES sanctuary_messages(id),
    resolved        BOOLEAN DEFAULT FALSE,
    resolved_at     TIMESTAMPTZ,
    details         JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sanc_interv_session ON sanctuary_interventions(session_id);


-- ─── Sanctuary Billing Events ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sanctuary_billing_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES family_sanctuary_sessions(id) ON DELETE CASCADE,
    event_type      VARCHAR(32) NOT NULL,          -- base_fee | coaching | assisted_response | threshold_alert
    amount_cents    INTEGER NOT NULL DEFAULT 0,
    member_id       UUID REFERENCES users(id),
    stripe_charge_id VARCHAR(255),
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sanc_billing_session ON sanctuary_billing_events(session_id);


-- ─── Sanctuary Archives ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sanctuary_archives (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES family_sanctuary_sessions(id) ON DELETE CASCADE,
    archive_type    VARCHAR(32) NOT NULL DEFAULT 'transcript',  -- transcript | summary | coach_briefing
    content         TEXT,
    blob_ref        TEXT,                          -- Azure Blob Storage reference
    generated_by    VARCHAR(32) DEFAULT 'system',  -- system | coach | ai
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sanc_archive_session ON sanctuary_archives(session_id);

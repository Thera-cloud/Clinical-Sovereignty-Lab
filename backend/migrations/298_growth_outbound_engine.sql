-- ============================================================================
-- 298_growth_outbound_engine.sql
-- Adaptive Growth Engine Phase 3: buyer leads, suppression, enrichment, replies.
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS buyer_leads (
    id                      BIGSERIAL PRIMARY KEY,
    email                   TEXT NOT NULL,
    email_norm              TEXT NOT NULL,
    first_name              TEXT,
    last_name               TEXT,
    company                 TEXT,
    title                   TEXT,
    npi                     TEXT,
    specialty               TEXT,
    state                   TEXT,
    source                  TEXT NOT NULL DEFAULT 'manual',
    icp_score               NUMERIC(8, 4) NOT NULL DEFAULT 0,
    status                  TEXT NOT NULL DEFAULT 'new'
                            CHECK (status IN (
                                'new', 'enriched', 'ready', 'queued', 'sent',
                                'replied', 'suppressed', 'erased', 'error'
                            )),
    enrichment              JSONB NOT NULL DEFAULT '{}'::jsonb,
    instantly_lead_id       TEXT,
    campaign_content_id     BIGINT REFERENCES marketing_content(id) ON DELETE SET NULL,
    last_error              TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Unique constraint (not just index) so ON CONFLICT (email_norm) works.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_buyer_leads_email_norm'
    ) THEN
        ALTER TABLE buyer_leads
            ADD CONSTRAINT uq_buyer_leads_email_norm UNIQUE (email_norm);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_buyer_leads_status_score
    ON buyer_leads (status, icp_score DESC);

CREATE TABLE IF NOT EXISTS outreach_suppression (
    id              BIGSERIAL PRIMARY KEY,
    email_norm      TEXT NOT NULL UNIQUE,
    reason          TEXT NOT NULL DEFAULT 'gdpr_erasure',
    source          TEXT NOT NULL DEFAULT 'system',
    permanent       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS enrichment_runs (
    id              BIGSERIAL PRIMARY KEY,
    lead_id         BIGINT REFERENCES buyer_leads(id) ON DELETE SET NULL,
    vendor          TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'skipped'
                    CHECK (status IN ('ok', 'skipped', 'error')),
    cost_usd        NUMERIC(12, 4) NOT NULL DEFAULT 0,
    detail          JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_enrichment_runs_lead
    ON enrichment_runs (lead_id, created_at DESC);

CREATE TABLE IF NOT EXISTS outreach_reply_queue (
    id              BIGSERIAL PRIMARY KEY,
    lead_id         BIGINT REFERENCES buyer_leads(id) ON DELETE SET NULL,
    email_norm      TEXT,
    body            TEXT NOT NULL DEFAULT '',
    classification  TEXT NOT NULL DEFAULT 'needs_review'
                    CHECK (classification IN (
                        'interested', 'not_interested', 'ooo', 'unsubscribe',
                        'bounce', 'needs_review'
                    )),
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'reviewed', 'dismissed')),
    meta            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_outreach_reply_pending
    ON outreach_reply_queue (status, created_at DESC)
    WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS landing_captures (
    id              BIGSERIAL PRIMARY KEY,
    landing         TEXT NOT NULL CHECK (landing IN ('providers', 'enterprise')),
    email_norm      TEXT NOT NULL,
    name            TEXT,
    org             TEXT,
    meta            JSONB NOT NULL DEFAULT '{}'::jsonb,
    drip_status     TEXT NOT NULL DEFAULT 'pending'
                    CHECK (drip_status IN ('pending', 'sent', 'skipped', 'error')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_landing_captures_email
    ON landing_captures (email_norm, created_at DESC);

INSERT INTO growth_config (key, value) VALUES
    ('outreach_daily_cap', '{"max_leads": 50, "max_campaigns": 3}'::jsonb),
    ('outreach_circuit_breaker', '{"fail_threshold": 3, "cooldown_minutes": 60}'::jsonb),
    ('icp_weights', '{
        "title_match": 0.35,
        "specialty_match": 0.35,
        "state_match": 0.15,
        "has_npi": 0.15
    }'::jsonb),
    ('icp_title_keywords', '["ceo","coo","director","owner","founder","practice manager","clinical director"]'::jsonb),
    ('icp_specialty_keywords', '["therapy","counseling","behavioral","psychiatry","coaching","mental health"]'::jsonb)
ON CONFLICT (key) DO NOTHING;

COMMIT;

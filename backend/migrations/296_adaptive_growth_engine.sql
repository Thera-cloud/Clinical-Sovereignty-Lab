-- ============================================================================
-- 296_adaptive_growth_engine.sql
-- Adaptive Growth Engine Phase 1: marketing_content substrate, BWAS config,
-- attribution/spend ledgers, SkyEye sibling link, CEO review audit support.
-- ============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. marketing_content (non-social: blog / email_drip / outreach / directory)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS marketing_content (
    id                  BIGSERIAL PRIMARY KEY,
    content_type        TEXT NOT NULL
                        CHECK (content_type IN ('blog', 'email_drip', 'outreach', 'directory_page')),
    platform            TEXT NOT NULL DEFAULT 'blog',
    audience            TEXT NOT NULL DEFAULT 'general',
    title               TEXT NOT NULL DEFAULT '',
    slug                TEXT,
    draft_body          TEXT NOT NULL DEFAULT '',
    html_body           TEXT,
    status              TEXT NOT NULL DEFAULT 'draft'
                        CHECK (status IN (
                            'draft', 'pending_review', 'approved', 'scheduled',
                            'published', 'rejected', 'unpublished', 'superseded'
                        )),
    keyword_id          BIGINT,
    keyword_cluster     TEXT,
    revision_of         BIGINT REFERENCES marketing_content(id) ON DELETE SET NULL,
    review_note         TEXT,
    scheduled_at        TIMESTAMPTZ,
    published_at        TIMESTAMPTZ,
    unpublished_at      TIMESTAMPTZ,
    public_path         TEXT,
    prompt_version      TEXT,
    generation_meta     JSONB NOT NULL DEFAULT '{}'::jsonb,
    performance         JSONB NOT NULL DEFAULT '{}'::jsonb,
    brand_checklist     JSONB NOT NULL DEFAULT '{}'::jsonb,
    approved_by         TEXT,
    approved_at         TIMESTAMPTZ,
    created_by          TEXT NOT NULL DEFAULT 'system',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_marketing_content_slug_live
    ON marketing_content (slug)
    WHERE slug IS NOT NULL AND status IN ('approved', 'scheduled', 'published');

CREATE INDEX IF NOT EXISTS idx_marketing_content_status
    ON marketing_content (status, scheduled_at NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_marketing_content_type_status
    ON marketing_content (content_type, status);

-- ---------------------------------------------------------------------------
-- 2. growth_config (BWAS weights + keyword priority knobs — admin/RED)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS growth_config (
    key         TEXT PRIMARY KEY,
    value       JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_by  TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO growth_config (key, value) VALUES
    ('bwas_stage_weights', '{
        "impression": 0.05,
        "engage": 0.10,
        "click": 0.15,
        "quiz_start": 0.20,
        "quiz_complete": 0.35,
        "signup": 1.00,
        "active_client": 2.50
    }'::jsonb),
    ('keyword_priority_weights', '{
        "volume_norm": 0.30,
        "intent": 0.25,
        "audience_value": 0.25,
        "buyer_prior": 0.20,
        "demand_prior_min": 1.0,
        "demand_prior_max": 1.5
    }'::jsonb),
    ('ceo_digest_batch_threshold', '{"n": 5}'::jsonb)
ON CONFLICT (key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3. Audit + credentials + attribution + spend
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS marketing_audit_log (
    id          BIGSERIAL PRIMARY KEY,
    content_id  BIGINT REFERENCES marketing_content(id) ON DELETE SET NULL,
    action      TEXT NOT NULL,
    actor       TEXT NOT NULL DEFAULT 'system',
    detail      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_marketing_audit_content
    ON marketing_audit_log (content_id, created_at DESC);

CREATE TABLE IF NOT EXISTS marketing_platform_credentials (
    platform        TEXT PRIMARY KEY,
    credentials     JSONB NOT NULL DEFAULT '{}'::jsonb,
    status          TEXT NOT NULL DEFAULT 'unconfigured',
    last_checked_at TIMESTAMPTZ,
    error_message   TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS growth_attribution_links (
    id              BIGSERIAL PRIMARY KEY,
    content_kind    TEXT NOT NULL CHECK (content_kind IN ('marketing', 'skyeye')),
    content_id      BIGINT NOT NULL,
    keyword_id      BIGINT,
    utm_campaign    TEXT,
    provider_slug   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_growth_attr_content
    ON growth_attribution_links (content_kind, content_id);

CREATE TABLE IF NOT EXISTS growth_spend_ledger (
    id          BIGSERIAL PRIMARY KEY,
    month       DATE NOT NULL,
    category    TEXT NOT NULL
                CHECK (category IN ('instantly', 'enrichment', 'studio_media', 'other')),
    amount_usd  NUMERIC(12, 4) NOT NULL DEFAULT 0,
    detail      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_growth_spend_month
    ON growth_spend_ledger (month, category);

-- ---------------------------------------------------------------------------
-- 4. SkyEye sibling glue
-- ---------------------------------------------------------------------------
ALTER TABLE skyeye_content_queue
    ADD COLUMN IF NOT EXISTS parent_marketing_content_id BIGINT
    REFERENCES marketing_content(id) ON DELETE SET NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_skyeye_parent_platform
    ON skyeye_content_queue (parent_marketing_content_id, platform)
    WHERE parent_marketing_content_id IS NOT NULL;

COMMIT;

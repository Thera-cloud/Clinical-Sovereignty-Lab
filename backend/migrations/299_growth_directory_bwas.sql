-- ============================================================================
-- 299_growth_directory_bwas.sql
-- Adaptive Growth Engine Phase 4: coach directory SEO + lead_events + BWAS.
-- Additive only. No provider_profiles table.
-- ============================================================================

BEGIN;

-- Extend coach_profiles for public directory (dual gate: consent + admin)
ALTER TABLE coach_profiles
    ADD COLUMN IF NOT EXISTS consent_public BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS public_slug TEXT,
    ADD COLUMN IF NOT EXISTS seo_bio_md TEXT,
    ADD COLUMN IF NOT EXISTS directory_published BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS directory_content_id BIGINT
        REFERENCES marketing_content(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS directory_city TEXT,
    ADD COLUMN IF NOT EXISTS directory_region TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS uq_coach_profiles_public_slug
    ON coach_profiles (public_slug)
    WHERE public_slug IS NOT NULL AND public_slug <> '';

CREATE INDEX IF NOT EXISTS idx_coach_profiles_directory_pub
    ON coach_profiles (directory_published)
    WHERE directory_published = true;

CREATE TABLE IF NOT EXISTS directory_pages (
    id              BIGSERIAL PRIMARY KEY,
    page_kind       TEXT NOT NULL CHECK (page_kind IN ('city', 'specialty')),
    slug            TEXT NOT NULL UNIQUE,
    title           TEXT NOT NULL,
    min_profiles    INT NOT NULL DEFAULT 3,
    profile_slugs   JSONB NOT NULL DEFAULT '[]'::jsonb,
    published       BOOLEAN NOT NULL DEFAULT false,
    html_path       TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Widen attribution content_kind for directory / quiz / try / outreach
ALTER TABLE growth_attribution_links
    DROP CONSTRAINT IF EXISTS growth_attribution_links_content_kind_check;
ALTER TABLE growth_attribution_links
    ADD CONSTRAINT growth_attribution_links_content_kind_check
    CHECK (content_kind IN (
        'marketing', 'skyeye', 'directory', 'quiz', 'try', 'outreach'
    ));

CREATE TABLE IF NOT EXISTS lead_events (
    id                  BIGSERIAL PRIMARY KEY,
    stage               TEXT NOT NULL CHECK (stage IN (
                            'impression', 'engage', 'click', 'quiz_start',
                            'quiz_complete', 'signup', 'active_client'
                        )),
    content_kind        TEXT CHECK (content_kind IN (
                            'marketing', 'skyeye', 'directory', 'quiz',
                            'try', 'outreach'
                        )),
    content_id          BIGINT,
    attribution_link_id BIGINT
        REFERENCES growth_attribution_links(id) ON DELETE SET NULL,
    provider_slug       TEXT,
    audience            TEXT,
    utm_campaign        TEXT,
    source              TEXT,
    meta                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lead_events_stage_time
    ON lead_events (stage, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_lead_events_provider
    ON lead_events (provider_slug)
    WHERE provider_slug IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_lead_events_content
    ON lead_events (content_kind, content_id)
    WHERE content_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS bwas_weekly (
    week_bucket     DATE NOT NULL,
    audience        TEXT NOT NULL DEFAULT 'general',
    content_kind    TEXT NOT NULL,
    content_id      BIGINT NOT NULL,
    score           NUMERIC(12, 4) NOT NULL DEFAULT 0,
    stage_counts    JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (week_bucket, audience, content_kind, content_id)
);

INSERT INTO growth_config (key, value) VALUES
    ('directory_min_profiles', '{"city": 3, "specialty": 3}'::jsonb)
ON CONFLICT (key) DO NOTHING;

COMMIT;

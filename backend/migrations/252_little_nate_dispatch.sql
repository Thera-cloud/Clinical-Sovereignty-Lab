-- Little Nate Dispatch — newsletter, Story Library, warm leads, growth
-- Additive only. QUANTUM-CRYSTAL-ARCH

CREATE TABLE IF NOT EXISTS newsletter_subscribers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL,
    phone_e164 TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'active', 'unsubscribed', 'suppressed', 'paused')),
    confirm_token_hash TEXT,
    confirm_token_expires_at TIMESTAMPTZ,
    unsubscribe_token_hash TEXT,
    consent_delivery_at TIMESTAMPTZ,
    consent_research_at TIMESTAMPTZ,
    consent_ip TEXT,
    consent_scope TEXT,
    has_used_20q BOOLEAN NOT NULL DEFAULT FALSE,
    engagement_score REAL NOT NULL DEFAULT 0,
    referred_count INT NOT NULL DEFAULT 0,
    referral_token_hash TEXT,
    locale TEXT DEFAULT 'en-US',
    source TEXT,
    utm_source TEXT,
    utm_medium TEXT,
    utm_campaign TEXT,
    suppressed_reason TEXT,
    last_open_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (email)
);

CREATE INDEX IF NOT EXISTS idx_newsletter_subscribers_status
    ON newsletter_subscribers (status);
CREATE INDEX IF NOT EXISTS idx_newsletter_subscribers_confirm
    ON newsletter_subscribers (confirm_token_hash)
    WHERE confirm_token_hash IS NOT NULL;

CREATE TABLE IF NOT EXISTS newsletter_issues (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN (
            'draft', 'researching', 'composing', 'critiquing',
            'in_review', 'approved', 'sent', 'rejected'
        )),
    topic TEXT,
    subject_line TEXT,
    opener TEXT,
    body_md TEXT,
    draft_body TEXT,
    final_body TEXT,
    techniques JSONB NOT NULL DEFAULT '[]'::jsonb,
    citations JSONB NOT NULL DEFAULT '[]'::jsonb,
    external_link TEXT,
    research_bundle JSONB NOT NULL DEFAULT '{}'::jsonb,
    experiment JSONB NOT NULL DEFAULT '{}'::jsonb,
    content_hash TEXT,
    crystal_id INTEGER,
    sent_at TIMESTAMPTZ,
    approved_at TIMESTAMPTZ,
    approved_by TEXT,
    rejected_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_newsletter_issues_status
    ON newsletter_issues (status);

CREATE TABLE IF NOT EXISTS newsletter_citations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    issue_id UUID NOT NULL REFERENCES newsletter_issues(id) ON DELETE CASCADE,
    source_name TEXT,
    year INT NOT NULL,
    url TEXT NOT NULL,
    modality TEXT,
    http_status_checked INT,
    verified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (year >= 2024)
);

CREATE TABLE IF NOT EXISTS newsletter_sends (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    issue_id UUID NOT NULL REFERENCES newsletter_issues(id) ON DELETE CASCADE,
    subscriber_id UUID NOT NULL REFERENCES newsletter_subscribers(id) ON DELETE CASCADE,
    provider_message_id TEXT,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'sent', 'delivered', 'opened', 'clicked', 'bounced', 'failed', 'skipped')),
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (issue_id, subscriber_id)
);

CREATE TABLE IF NOT EXISTS newsletter_send_events (
    id BIGSERIAL PRIMARY KEY,
    issue_id UUID REFERENCES newsletter_issues(id) ON DELETE SET NULL,
    subscriber_id UUID REFERENCES newsletter_subscribers(id) ON DELETE SET NULL,
    provider_message_id TEXT,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_newsletter_send_events_issue
    ON newsletter_send_events (issue_id, created_at DESC);

CREATE TABLE IF NOT EXISTS newsletter_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    issue_id UUID NOT NULL REFERENCES newsletter_issues(id) ON DELETE CASCADE,
    subscriber_id UUID REFERENCES newsletter_subscribers(id) ON DELETE SET NULL,
    helpful_score INT CHECK (helpful_score IS NULL OR (helpful_score BETWEEN 1 AND 5)),
    liked BOOLEAN,
    reply_text TEXT,
    reply_sanitized TEXT,
    themes JSONB NOT NULL DEFAULT '[]'::jsonb,
    rating_token_hash TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS newsletter_library_stats (
    slug TEXT PRIMARY KEY REFERENCES newsletter_issues(slug) ON DELETE CASCADE,
    view_count BIGINT NOT NULL DEFAULT 0,
    chat_reference_count BIGINT NOT NULL DEFAULT 0,
    share_count BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS newsletter_symbolic_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind TEXT NOT NULL
        CHECK (kind IN ('fact', 'rule', 'outcome', 'style_note', 'decision_log', 'observation')),
    content TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    contradiction_count INT NOT NULL DEFAULT 0,
    source_issue_id UUID REFERENCES newsletter_issues(id) ON DELETE SET NULL,
    source_task_id TEXT,
    scope TEXT NOT NULL DEFAULT 'active'
        CHECK (scope IN ('active', 'archived')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_newsletter_symbolic_active
    ON newsletter_symbolic_memory (scope, confidence DESC)
    WHERE scope = 'active';

CREATE TABLE IF NOT EXISTS newsletter_topic_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic_key TEXT NOT NULL,
    title TEXT,
    last_used_at TIMESTAMPTZ,
    use_count INT NOT NULL DEFAULT 0,
    fatigue_score REAL NOT NULL DEFAULT 0,
    self_cite_slug TEXT,
    seasonal_window TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (topic_key)
);

CREATE TABLE IF NOT EXISTS newsletter_chat_signals (
    id BIGSERIAL PRIMARY KEY,
    theme TEXT NOT NULL,
    week_bucket DATE NOT NULL,
    count_bucket INT NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (theme, week_bucket)
);

CREATE TABLE IF NOT EXISTS newsletter_warm_leads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT,
    phone_e164 TEXT,
    platform TEXT,
    handle TEXT,
    platform_user_id TEXT,
    contact_type TEXT NOT NULL DEFAULT 'email'
        CHECK (contact_type IN ('email', 'handle', 'phone')),
    source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'invited', 'converted', 'suppressed')),
    last_invited_at TIMESTAMPTZ,
    consent_notes TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_newsletter_warm_leads_email
    ON newsletter_warm_leads (LOWER(email))
    WHERE email IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_newsletter_warm_leads_handle
    ON newsletter_warm_leads (platform, handle)
    WHERE handle IS NOT NULL AND platform IS NOT NULL;

CREATE TABLE IF NOT EXISTS newsletter_growth_ledger (
    id BIGSERIAL PRIMARY KEY,
    day DATE NOT NULL,
    channel TEXT NOT NULL,
    subscribers_gained INT NOT NULL DEFAULT 0,
    invites_sent INT NOT NULL DEFAULT 0,
    conversions INT NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (day, channel)
);

CREATE TABLE IF NOT EXISTS newsletter_topic_forecast (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic_key TEXT NOT NULL,
    seasonal_label TEXT,
    target_week DATE,
    news_velocity REAL NOT NULL DEFAULT 0,
    foresight_score REAL NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES (
    'newsletter_check_count',
    '{"expected": 10, "description": "Little Nate Dispatch trust checks", "updated": "2026-07-18"}'::jsonb
)
ON CONFLICT (parameter_key) DO UPDATE
SET parameter_value = EXCLUDED.parameter_value;

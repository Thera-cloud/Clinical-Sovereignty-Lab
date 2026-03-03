-- ============================================================================
-- Migration 052: Data Consolidation — PostgreSQL as Single Source of Truth
-- Creates tables to replace JSON file dependencies in admin.py and dashboard
-- endpoints, enabling both backend and bridge containers to read from the
-- same authoritative store.
-- ============================================================================

-- Client metrics snapshots (replaces Vaults/Clients/{id}/metrics.json)
CREATE TABLE IF NOT EXISTS client_metrics (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    hardware_id     TEXT NOT NULL,
    c_emo           DOUBLE PRECISION DEFAULT 0,
    e_warmth        DOUBLE PRECISION DEFAULT 0,
    t_tunnel        DOUBLE PRECISION DEFAULT 0,
    gap             DOUBLE PRECISION DEFAULT 0,
    velocity        DOUBLE PRECISION DEFAULT 0,
    quantum         DOUBLE PRECISION DEFAULT 0,
    anxiety_level   DOUBLE PRECISION DEFAULT 0,
    depression_indicators DOUBLE PRECISION DEFAULT 0,
    stress_level    DOUBLE PRECISION DEFAULT 0,
    engagement      DOUBLE PRECISION DEFAULT 0,
    session_count   INTEGER DEFAULT 0,
    breakthrough_count INTEGER DEFAULT 0,
    homework_completion_rate DOUBLE PRECISION DEFAULT 0,
    risk_level      TEXT DEFAULT 'low',
    crisis_count    INTEGER DEFAULT 0,
    mood_current    TEXT DEFAULT 'neutral',
    mood_trend      TEXT DEFAULT 'stable',
    crisis_perception JSONB DEFAULT '{}',
    shame_profile   JSONB DEFAULT '{}',
    pmb             JSONB DEFAULT '{}',
    nevedal_state   JSONB DEFAULT '{}',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_client_metrics_user
    ON client_metrics(user_id);
CREATE INDEX IF NOT EXISTS idx_client_metrics_hardware
    ON client_metrics(hardware_id);

-- Daily analytics (replaces analytics.json daily_stats)
CREATE TABLE IF NOT EXISTS daily_analytics (
    id              BIGSERIAL PRIMARY KEY,
    date            DATE NOT NULL,
    logins          INTEGER DEFAULT 0,
    registrations   INTEGER DEFAULT 0,
    messages_sent   INTEGER DEFAULT 0,
    tokens_used     INTEGER DEFAULT 0,
    sessions_started INTEGER DEFAULT 0,
    sessions_completed INTEGER DEFAULT 0,
    crisis_events   INTEGER DEFAULT 0,
    active_users    INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_analytics_date
    ON daily_analytics(date);

-- Platform totals (replaces analytics.json platform_totals)
CREATE TABLE IF NOT EXISTS platform_totals (
    id              BIGSERIAL PRIMARY KEY,
    total_sessions  BIGINT DEFAULT 0,
    total_messages  BIGINT DEFAULT 0,
    total_tokens_used BIGINT DEFAULT 0,
    total_crisis_resolved INTEGER DEFAULT 0,
    total_breakthroughs INTEGER DEFAULT 0,
    total_users_registered INTEGER DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed single row for platform totals
INSERT INTO platform_totals (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- Crisis events log (replaces crisis_log.json)
CREATE TABLE IF NOT EXISTS crisis_events (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
    user_name       TEXT,
    hardware_id     TEXT,
    risk_level      TEXT DEFAULT 'medium',
    reason          TEXT,
    keywords        TEXT[],
    session_id      TEXT,
    family_id       TEXT,
    resolved        BOOLEAN DEFAULT FALSE,
    resolved_at     TIMESTAMPTZ,
    resolved_by     TEXT,
    resolution_notes TEXT,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_crisis_events_user
    ON crisis_events(user_id);
CREATE INDEX IF NOT EXISTS idx_crisis_events_resolved
    ON crisis_events(resolved);
CREATE INDEX IF NOT EXISTS idx_crisis_events_timestamp
    ON crisis_events(timestamp DESC);

-- Dynamic assessments (for new Assessment Engine)
CREATE TABLE IF NOT EXISTS dynamic_assessments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category        TEXT NOT NULL,
    title           TEXT NOT NULL,
    questions       JSONB NOT NULL DEFAULT '[]',
    context_summary TEXT,
    trigger_reason  TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    score           DOUBLE PRECISION,
    insights        JSONB DEFAULT '{}',
    growth_markers  JSONB DEFAULT '[]',
    nate_reflection TEXT,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_assessments_user
    ON dynamic_assessments(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_assessments_status
    ON dynamic_assessments(status);
CREATE INDEX IF NOT EXISTS idx_assessments_category
    ON dynamic_assessments(user_id, category);

-- Assessment responses (individual answers)
CREATE TABLE IF NOT EXISTS assessment_responses (
    id              BIGSERIAL PRIMARY KEY,
    assessment_id   UUID NOT NULL REFERENCES dynamic_assessments(id) ON DELETE CASCADE,
    question_index  INTEGER NOT NULL,
    question_text   TEXT NOT NULL,
    answer_text     TEXT,
    answer_value    INTEGER,
    reflection      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_assessment_responses_assessment
    ON assessment_responses(assessment_id);

-- Coach metrics (for coach performance tracking)
CREATE TABLE IF NOT EXISTS coach_metrics (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    hardware_id     TEXT NOT NULL,
    total_sessions  INTEGER DEFAULT 0,
    active_clients  INTEGER DEFAULT 0,
    therapeutic_presence_score DOUBLE PRECISION DEFAULT 0,
    talk_time_ratio DOUBLE PRECISION DEFAULT 0,
    reflection_frequency DOUBLE PRECISION DEFAULT 0,
    detected_techniques TEXT[] DEFAULT '{}',
    ai_collab_score DOUBLE PRECISION DEFAULT 0,
    retention_rate  DOUBLE PRECISION DEFAULT 0,
    ytd_earnings    NUMERIC(10,2) DEFAULT 0,
    specialty       TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_coach_metrics_user
    ON coach_metrics(user_id);

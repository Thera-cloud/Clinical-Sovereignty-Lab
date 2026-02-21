-- 049: Sovereign Unification Tables
-- Bridges all isolated wisdom sources into one coherent intelligence

-- Accumulated insights from periodic self-reflection across all systems
CREATE TABLE IF NOT EXISTS sovereign_insight_journal (
    id              SERIAL PRIMARY KEY,
    insight_type    TEXT NOT NULL,  -- nevedal_coherence, therapy_pattern, marketing_performance,
                                   -- livestream_learning, expression_resonance, web_wisdom,
                                   -- self_reflection, meta_insight
    category        TEXT,           -- technique, trend, gap, opportunity, warning
    title           TEXT NOT NULL,
    content         TEXT NOT NULL,
    evidence        JSONB DEFAULT '{}',   -- source data references
    coherence_score FLOAT,                -- Nevedal C_emo score for this insight
    impact_score    FLOAT DEFAULT 0,      -- how actionable (0-1)
    applied         BOOLEAN DEFAULT FALSE, -- has this insight been acted on
    applied_to      TEXT[],               -- which systems used this insight
    source_systems  TEXT[] NOT NULL,       -- which systems contributed
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ            -- some insights are time-bound
);

-- External content Nate reads and learns from
CREATE TABLE IF NOT EXISTS web_wisdom (
    id              SERIAL PRIMARY KEY,
    url             TEXT NOT NULL,
    source_type     TEXT NOT NULL,  -- rss, social_link, article, competitor, research
    title           TEXT,
    summary         TEXT,           -- AI-generated summary
    key_insights    JSONB DEFAULT '[]',
    emotional_resonance FLOAT,     -- Nevedal C_emo score
    relevance_score FLOAT,         -- relevance to Sovereign Sanctuary mission
    themes          TEXT[],
    applied_to_content BOOLEAN DEFAULT FALSE,
    metadata        JSONB DEFAULT '{}',
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Expression engagement tracking (feedback loop)
CREATE TABLE IF NOT EXISTS expression_engagement (
    id              SERIAL PRIMARY KEY,
    expression_id   INTEGER,
    platform        TEXT NOT NULL,
    post_id         TEXT,
    likes           INTEGER DEFAULT 0,
    comments        INTEGER DEFAULT 0,
    shares          INTEGER DEFAULT 0,
    engagement_rate FLOAT DEFAULT 0,
    emotional_theme TEXT,
    checked_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_journal_type ON sovereign_insight_journal(insight_type);
CREATE INDEX idx_journal_created ON sovereign_insight_journal(created_at DESC);
CREATE INDEX idx_journal_applied ON sovereign_insight_journal(applied) WHERE NOT applied;
CREATE INDEX idx_web_wisdom_type ON web_wisdom(source_type);
CREATE INDEX idx_web_wisdom_fetched ON web_wisdom(fetched_at DESC);
CREATE INDEX idx_expression_engagement ON expression_engagement(expression_id);

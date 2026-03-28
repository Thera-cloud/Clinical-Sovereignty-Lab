-- Migration 119: Nate Intelligence Crystals
-- Self-learning knowledge crystallization system

CREATE TABLE IF NOT EXISTS nate_intelligence_crystals (
    id              SERIAL PRIMARY KEY,
    crystal_text    TEXT NOT NULL,
    domain          VARCHAR(50) NOT NULL DEFAULT 'general',
    topics          TEXT[] DEFAULT '{}',
    scope           VARCHAR(50) NOT NULL DEFAULT 'global',
    source_ids      INTEGER[] DEFAULT '{}',
    source_count    INTEGER DEFAULT 1,
    generation      INTEGER DEFAULT 0,
    confidence      REAL DEFAULT 0.5,
    content_hash    VARCHAR(64) NOT NULL,
    embedding_id    VARCHAR(128),
    context_start   TIMESTAMPTZ,
    context_end     TIMESTAMPTZ,
    last_recalled_at TIMESTAMPTZ,
    recall_count    INTEGER DEFAULT 0,
    superseded_by   INTEGER REFERENCES nate_intelligence_crystals(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_crystals_domain ON nate_intelligence_crystals(domain);
CREATE INDEX IF NOT EXISTS idx_crystals_scope ON nate_intelligence_crystals(scope);
CREATE INDEX IF NOT EXISTS idx_crystals_confidence ON nate_intelligence_crystals(confidence);
CREATE INDEX IF NOT EXISTS idx_crystals_generation ON nate_intelligence_crystals(generation);
CREATE INDEX IF NOT EXISTS idx_crystals_recalled ON nate_intelligence_crystals(last_recalled_at);
CREATE INDEX IF NOT EXISTS idx_crystals_hash ON nate_intelligence_crystals(content_hash);
CREATE INDEX IF NOT EXISTS idx_crystals_superseded ON nate_intelligence_crystals(superseded_by)
    WHERE superseded_by IS NULL;

-- Web wisdom storage for internet search results
CREATE TABLE IF NOT EXISTS web_wisdom (
    id              SERIAL PRIMARY KEY,
    query           TEXT NOT NULL,
    source_url      TEXT,
    title           TEXT,
    snippet         TEXT,
    full_text       TEXT,
    domain_tag      VARCHAR(50) DEFAULT 'general',
    relevance_score REAL DEFAULT 0.5,
    searched_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    indexed_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_web_wisdom_query ON web_wisdom USING gin(to_tsvector('english', query));
CREATE INDEX IF NOT EXISTS idx_web_wisdom_searched ON web_wisdom(searched_at);

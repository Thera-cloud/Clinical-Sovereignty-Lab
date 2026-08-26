-- Migration 430: AlphaLN Phase B — synthetic client profiles + isolated research log
--
-- Additive only. Namespace `alphaln_*`. See cursor rule
-- alphaln-twin-isolation.mdc (Invariant 2: never write production crystals).
--
-- Note: 428/429 are already taken (pack drafts / workbook ingest).
-- Feature flag: ENABLE_ALPHALN_GYM (default false).

CREATE TABLE IF NOT EXISTS alphaln_synthetic_profiles (
    profile_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    base_persona TEXT NOT NULL,
    co_occurring_patterns JSONB NOT NULL DEFAULT '[]'::jsonb,
    trigger_context TEXT,
    difficulty_level INT NOT NULL DEFAULT 1,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    combo_key TEXT NOT NULL DEFAULT ''
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_alphaln_synthetic_profiles_combo
    ON alphaln_synthetic_profiles (base_persona, combo_key, trigger_context);

CREATE INDEX IF NOT EXISTS idx_alphaln_synthetic_profiles_active
    ON alphaln_synthetic_profiles (is_active, difficulty_level);

COMMENT ON TABLE alphaln_synthetic_profiles IS
    'AlphaLN Phase B synthetic client library. Gym-only; never a live client.';

-- Isolated research findings (source=alphaln_research). NOT nate_intelligence_crystals.
CREATE TABLE IF NOT EXISTS alphaln_research_findings (
    id                 BIGSERIAL PRIMARY KEY,
    conversation_id    UUID,
    query_text         TEXT NOT NULL,
    findings           JSONB NOT NULL DEFAULT '[]'::jsonb,
    source             TEXT NOT NULL DEFAULT 'alphaln_research',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alphaln_research_findings_created
    ON alphaln_research_findings (created_at DESC);

COMMENT ON TABLE alphaln_research_findings IS
    'AlphaLN admin research log. Isolated from production crystal tables.';

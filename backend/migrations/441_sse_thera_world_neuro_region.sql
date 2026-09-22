-- 441: Thera-world Neuro region — additive only. QUANTUM-CRYSTAL-ARCH
-- Origin (Path of Five) columns, defaults and rows are untouched.
-- Engine-only vocabulary lives here (neuro_domain etc.); never exposed to client copy.

ALTER TABLE sse_user_journeys
    ADD COLUMN IF NOT EXISTS current_region TEXT NOT NULL DEFAULT 'origin',
    ADD COLUMN IF NOT EXISTS neuro_biome TEXT,
    ADD COLUMN IF NOT EXISTS neuro_scores JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS neuro_last_scored_at TIMESTAMPTZ;

ALTER TABLE sse_panel_log
    ADD COLUMN IF NOT EXISTS region TEXT NOT NULL DEFAULT 'origin',
    ADD COLUMN IF NOT EXISTS neuro_domain TEXT,
    ADD COLUMN IF NOT EXISTS neuro_champion TEXT,
    ADD COLUMN IF NOT EXISTS panel_metadata JSONB DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_sse_panel_log_user_region
    ON sse_panel_log (user_id, region, generated_at DESC);

-- Append-only score history (coach/engine analytics; H_d and H are derived, not stored as truth).
CREATE TABLE IF NOT EXISTS sse_neuro_score_log (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    scores JSONB NOT NULL,
    h_d JSONB NOT NULL,
    h NUMERIC(6,4) NOT NULL,
    selected_biome TEXT,
    champion TEXT,
    panel_id UUID,
    source TEXT NOT NULL DEFAULT 'crystal_stems',
    scored_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sse_neuro_score_log_user_time
    ON sse_neuro_score_log (user_id, scored_at DESC);

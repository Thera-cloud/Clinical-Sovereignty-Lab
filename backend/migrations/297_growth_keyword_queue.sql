-- ============================================================================
-- 297_growth_keyword_queue.sql
-- Adaptive Growth Engine Phase 2: keyword_queue + factory knobs.
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS keyword_queue (
    id                  BIGSERIAL PRIMARY KEY,
    keyword             TEXT NOT NULL,
    cluster             TEXT,
    audience            TEXT NOT NULL DEFAULT 'general',
    volume_norm         NUMERIC(6, 4) NOT NULL DEFAULT 0
                        CHECK (volume_norm >= 0 AND volume_norm <= 1),
    intent              NUMERIC(6, 4) NOT NULL DEFAULT 0
                        CHECK (intent >= 0 AND intent <= 1),
    audience_value      NUMERIC(6, 4) NOT NULL DEFAULT 0
                        CHECK (audience_value >= 0 AND audience_value <= 1),
    buyer_prior         NUMERIC(6, 4) NOT NULL DEFAULT 0
                        CHECK (buyer_prior >= 0 AND buyer_prior <= 1),
    -- Phase 2b: try_theme_weekly demand boost (bound 1.0–1.5). v1 always 1.0.
    demand_prior        NUMERIC(6, 4) NOT NULL DEFAULT 1.0
                        CHECK (demand_prior >= 1.0 AND demand_prior <= 1.5),
    priority_score      NUMERIC(12, 6) NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'queued'
                        CHECK (status IN (
                            'queued', 'in_progress', 'done', 'skipped', 'blocked'
                        )),
    last_content_id     BIGINT REFERENCES marketing_content(id) ON DELETE SET NULL,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- App normalizes keyword+audience to lowercase on write.
    CONSTRAINT uq_keyword_queue_keyword_audience UNIQUE (keyword, audience)
);

CREATE INDEX IF NOT EXISTS idx_keyword_queue_priority
    ON keyword_queue (status, priority_score DESC)
    WHERE status = 'queued';

-- Optional FK from marketing_content.keyword_id → keyword_queue
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_marketing_content_keyword'
    ) THEN
        ALTER TABLE marketing_content
            ADD CONSTRAINT fk_marketing_content_keyword
            FOREIGN KEY (keyword_id) REFERENCES keyword_queue(id) ON DELETE SET NULL;
    END IF;
END $$;

INSERT INTO growth_config (key, value) VALUES
    ('factory_batch_size', '{"n": 2}'::jsonb),
    ('factory_social_platforms', '["x", "linkedin"]'::jsonb),
    ('studio_media_mode', '{"mode": "text_only", "allow_media_when_budget_ok": true}'::jsonb)
ON CONFLICT (key) DO NOTHING;

COMMIT;

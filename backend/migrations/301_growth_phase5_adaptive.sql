-- ============================================================================
-- 301_growth_phase5_adaptive.sql
-- Adaptive Growth Engine Phase 5: A/B experiment fields + marketing_policies.
-- ============================================================================

BEGIN;

ALTER TABLE content_ab_tests
    ADD COLUMN IF NOT EXISTS hypothesis TEXT,
    ADD COLUMN IF NOT EXISTS experiment_scope TEXT,
    ADD COLUMN IF NOT EXISTS min_sample INT DEFAULT 50,
    ADD COLUMN IF NOT EXISTS verdict TEXT,
    ADD COLUMN IF NOT EXISTS crystal_ref TEXT;

CREATE TABLE IF NOT EXISTS marketing_policies (
    id          SERIAL PRIMARY KEY,
    policy_key  TEXT NOT NULL UNIQUE,
    stance      TEXT NOT NULL DEFAULT 'YELLOW'
                CHECK (stance IN ('GREEN', 'YELLOW', 'RED')),
    body        TEXT NOT NULL DEFAULT '',
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_marketing_policies_stance
    ON marketing_policies (stance);

INSERT INTO growth_config (key, value, updated_at)
VALUES (
    'growth_diagnostics_interval_s',
    '{"n": 3600}'::jsonb,
    NOW()
)
ON CONFLICT (key) DO NOTHING;

COMMIT;

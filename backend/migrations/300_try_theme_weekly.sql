-- ============================================================================
-- 300_try_theme_weekly.sql
-- Adaptive Growth Engine Phase 4b: anonymized try.html theme aggregates.
-- Never stores utterances, emails, or device ids.
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS try_theme_weekly (
    theme         TEXT NOT NULL,
    week_bucket   DATE NOT NULL,
    count_bucket  INT NOT NULL DEFAULT 0,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (theme, week_bucket),
    CONSTRAINT try_theme_weekly_theme_not_ops
        CHECK (theme <> 'ops_only' AND theme <> '')
);

CREATE INDEX IF NOT EXISTS idx_try_theme_weekly_week
    ON try_theme_weekly (week_bucket DESC, count_bucket DESC);

COMMIT;

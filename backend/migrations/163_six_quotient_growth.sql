-- Migration 163: Six-Quotient Growth Engine
-- Tracks per-interaction quotient exercise, quality signals, and anti-patterns.
-- This is how Little Nate measures his own clinical growth over time.

CREATE TABLE IF NOT EXISTS six_quotient_growth (
    id              SERIAL PRIMARY KEY,
    user_id         VARCHAR(128),
    quotients_exercised TEXT[] DEFAULT '{}',
    quality_positive TEXT[] DEFAULT '{}',
    quality_negative TEXT[] DEFAULT '{}',
    growth_score    INTEGER DEFAULT 0,
    provider        VARCHAR(64) DEFAULT '',
    user_snippet    TEXT DEFAULT '',
    nate_snippet    TEXT DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sqg_created_at ON six_quotient_growth (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sqg_user_id ON six_quotient_growth (user_id);
CREATE INDEX IF NOT EXISTS idx_sqg_quotients ON six_quotient_growth USING GIN (quotients_exercised);

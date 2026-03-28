-- Migration 127: Learning Loop Insights
-- Stores pattern summaries from LearningLoopAgent for infinite intelligence growth

CREATE TABLE IF NOT EXISTS learning_loop_insights (
    id SERIAL PRIMARY KEY,
    pattern_type VARCHAR(64) NOT NULL,
    platform VARCHAR(64) NOT NULL DEFAULT 'system',
    event_count INTEGER NOT NULL DEFAULT 0,
    confidence NUMERIC(4, 2) NOT NULL DEFAULT 0,
    peak_hour_utc INTEGER NOT NULL DEFAULT 0,
    insight_data JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_learning_loop_insights_created
    ON learning_loop_insights(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_learning_loop_insights_pattern
    ON learning_loop_insights(pattern_type, platform);

-- ============================================================================
-- Migration 012: Performance Indexes
-- Adds missing indexes to sessions table and other high-query tables
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_coach_id ON sessions(coach_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_scheduled ON sessions(scheduled_at);
CREATE INDEX IF NOT EXISTS idx_nevedal_metrics_user_recorded ON nevedal_metrics(user_id, recorded_at DESC);

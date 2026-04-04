ALTER TABLE sse_panel_log ADD COLUMN IF NOT EXISTS viewed_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_panel_log_viewed ON sse_panel_log(user_id, viewed_at) WHERE viewed_at IS NOT NULL;

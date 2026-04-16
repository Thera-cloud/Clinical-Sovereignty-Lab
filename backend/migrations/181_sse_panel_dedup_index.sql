-- Migration 181: Prevent duplicate daily journey panels per user per day.
-- Root cause: lifespan double-fire creates two SSEOrchestrator instances,
-- both firing the 03:15 cron, racing past the SELECT dedup check.

CREATE UNIQUE INDEX IF NOT EXISTS idx_panel_log_user_day_journey
ON sse_panel_log (user_id, (generated_at::date), panel_type)
WHERE panel_type = 'journey';

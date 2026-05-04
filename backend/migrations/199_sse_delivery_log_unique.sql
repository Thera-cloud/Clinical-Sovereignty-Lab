-- Migration 199: SSE delivery log unique constraint
-- Prevents duplicate success rows from multi-instance scheduler writes.
-- A partial expression index lets ON CONFLICT target it in delivery_runtime._log.
--
-- Only 'success' rows are covered so failure retries are always logged.

CREATE UNIQUE INDEX IF NOT EXISTS ux_sse_delivery_slot
    ON sse_delivery_generation_log (
        user_id,
        storyboard_id,
        generation_type,
        (generated_at::date)
    )
    WHERE status = 'success';

-- Duplicate rows from the two-scheduler bleed-through can be cleaned with:
--
-- DELETE FROM sse_delivery_generation_log a
-- USING sse_delivery_generation_log b
-- WHERE a.status = 'success'
--   AND b.status = 'success'
--   AND a.user_id = b.user_id
--   AND a.storyboard_id = b.storyboard_id
--   AND a.generation_type = b.generation_type
--   AND a.generated_at::date = b.generated_at::date
--   AND a.log_id < b.log_id;   -- keep the earlier of each duplicate pair

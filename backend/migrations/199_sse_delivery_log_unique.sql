-- Migration 199: SSE delivery log unique constraint
-- Prevents duplicate success rows from multi-instance scheduler writes.
-- Adds a generation_date column (UTC date at insert time) so we can create
-- a plain unique index without the IMMUTABLE issue of timestamptz::date.

ALTER TABLE sse_delivery_generation_log
    ADD COLUMN IF NOT EXISTS generation_date date;

-- Back-fill from generated_at for existing rows (UTC)
UPDATE sse_delivery_generation_log
   SET generation_date = (generated_at AT TIME ZONE 'UTC')::date
 WHERE generation_date IS NULL;

-- Partial unique index: only one 'success' row per slot per UTC day
CREATE UNIQUE INDEX IF NOT EXISTS ux_sse_delivery_slot
    ON sse_delivery_generation_log (user_id, storyboard_id, generation_type, generation_date)
    WHERE status = 'success';

-- To clean up existing duplicates, run manually:
--
-- DELETE FROM sse_delivery_generation_log a
-- USING sse_delivery_generation_log b
-- WHERE a.status = 'success'
--   AND b.status = 'success'
--   AND a.user_id = b.user_id
--   AND a.storyboard_id = b.storyboard_id
--   AND a.generation_type = b.generation_type
--   AND a.generation_date = b.generation_date
--   AND a.log_id < b.log_id;

-- Migration 220: Sync scheduled_at with scheduled_start for payment agent + calendar
-- Fixes coach-scheduled Zoom sessions auto-cancelled because scheduled_at defaulted to NOW().

UPDATE coaching_sessions
SET scheduled_at = scheduled_start,
    payment_due_at = scheduled_start - INTERVAL '72 hours',
    cancellation_deadline = scheduled_start - INTERVAL '24 hours',
    updated_at = NOW()
WHERE scheduled_start IS NOT NULL
  AND (
    scheduled_at IS NULL
    OR scheduled_at IS DISTINCT FROM scheduled_start
  );

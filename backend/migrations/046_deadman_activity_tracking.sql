-- =============================================================================
-- Migration 046: Deadman Switch Activity Tracking
-- Adds last_nate_message_at to users table so the Deadman Switch can detect
-- Little Nate conversation activity as a sign of life.
-- =============================================================================

BEGIN;

ALTER TABLE users ADD COLUMN IF NOT EXISTS last_nate_message_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_users_last_nate_msg
    ON users(last_nate_message_at)
    WHERE last_nate_message_at IS NOT NULL;

COMMIT;

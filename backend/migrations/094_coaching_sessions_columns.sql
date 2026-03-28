-- Migration 094: Add missing columns to coaching_sessions table
-- The code (pg_data_helpers.py) expects these columns for session CRUD operations.
-- Without them, load_sessions_pg and upsert_session_pg fail silently,
-- forcing fallback to encrypted JSON which causes stale-session conflicts.

ALTER TABLE coaching_sessions ADD COLUMN IF NOT EXISTS family_id TEXT DEFAULT '';
ALTER TABLE coaching_sessions ADD COLUMN IF NOT EXISTS session_type TEXT DEFAULT 'CLIENT';
ALTER TABLE coaching_sessions ADD COLUMN IF NOT EXISTS scheduled_start TIMESTAMPTZ;
ALTER TABLE coaching_sessions ADD COLUMN IF NOT EXISTS scheduled_end TIMESTAMPTZ;
ALTER TABLE coaching_sessions ADD COLUMN IF NOT EXISTS zoom_host_url TEXT DEFAULT '';
ALTER TABLE coaching_sessions ADD COLUMN IF NOT EXISTS notes TEXT DEFAULT '';
ALTER TABLE coaching_sessions ADD COLUMN IF NOT EXISTS topics_covered JSONB DEFAULT '[]'::jsonb;
ALTER TABLE coaching_sessions ADD COLUMN IF NOT EXISTS homework_assigned JSONB DEFAULT '[]'::jsonb;
ALTER TABLE coaching_sessions ADD COLUMN IF NOT EXISTS recording_url TEXT DEFAULT '';

-- Backfill scheduled_start from scheduled_at for existing rows
UPDATE coaching_sessions
SET scheduled_start = scheduled_at
WHERE scheduled_start IS NULL AND scheduled_at IS NOT NULL;

-- Backfill scheduled_end from scheduled_at + duration (default 50 min)
UPDATE coaching_sessions
SET scheduled_end = scheduled_at + (COALESCE(duration_minutes, 50) * INTERVAL '1 minute')
WHERE scheduled_end IS NULL AND scheduled_at IS NOT NULL;

-- Add unique constraint on session_id if not already present
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'coaching_sessions_session_id_key'
        AND conrelid = 'coaching_sessions'::regclass
    ) THEN
        BEGIN
            ALTER TABLE coaching_sessions ADD CONSTRAINT coaching_sessions_session_id_key UNIQUE (session_id);
        EXCEPTION WHEN unique_violation THEN
            NULL;
        END;
    END IF;
END $$;

-- Index for faster coach schedule queries
CREATE INDEX IF NOT EXISTS idx_coaching_sessions_coach_start
    ON coaching_sessions(coach_id, scheduled_start);

CREATE INDEX IF NOT EXISTS idx_coaching_sessions_status
    ON coaching_sessions(status);

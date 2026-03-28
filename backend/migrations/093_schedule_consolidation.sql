-- Migration 093: Schedule Consolidation
-- Reconcile coach_availability schema (001 vs 081) and add coach_consultations table

-- Ensure all columns from both schema versions exist
ALTER TABLE coach_availability ADD COLUMN IF NOT EXISTS recurring BOOLEAN DEFAULT TRUE;
ALTER TABLE coach_availability ADD COLUMN IF NOT EXISTS calendar_sync_email TEXT;
ALTER TABLE coach_availability ADD COLUMN IF NOT EXISTS is_available BOOLEAN DEFAULT TRUE;
ALTER TABLE coach_availability ADD COLUMN IF NOT EXISTS max_sessions_per_slot INTEGER DEFAULT 1;
ALTER TABLE coach_availability ADD COLUMN IF NOT EXISTS session_duration_minutes INTEGER DEFAULT 60;
ALTER TABLE coach_availability ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

-- Index for fast availability lookups by coach + day
CREATE INDEX IF NOT EXISTS idx_coach_availability_coach_day
    ON coach_availability(coach_id, day_of_week);

-- Index for specific date lookups
CREATE INDEX IF NOT EXISTS idx_coach_availability_specific_date
    ON coach_availability(coach_id, specific_date)
    WHERE specific_date IS NOT NULL;

-- Assistant-coach consultation tracking
CREATE TABLE IF NOT EXISTS coach_consultations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    assistant_username TEXT NOT NULL,
    master_username TEXT NOT NULL,
    scheduled_start TIMESTAMPTZ NOT NULL,
    scheduled_end TIMESTAMPTZ NOT NULL,
    status TEXT DEFAULT 'scheduled' CHECK (status IN ('scheduled', 'completed', 'cancelled')),
    is_free BOOLEAN DEFAULT FALSE,
    notes TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(assistant_username, master_username, scheduled_start)
);

CREATE INDEX IF NOT EXISTS idx_coach_consultations_assistant
    ON coach_consultations(assistant_username, scheduled_start);

CREATE INDEX IF NOT EXISTS idx_coach_consultations_master
    ON coach_consultations(master_username, scheduled_start);

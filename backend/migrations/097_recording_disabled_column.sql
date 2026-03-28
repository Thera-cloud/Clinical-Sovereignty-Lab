-- Add recording_disabled column to coaching_sessions for per-session recording control
ALTER TABLE coaching_sessions ADD COLUMN IF NOT EXISTS recording_disabled BOOLEAN DEFAULT FALSE;

-- Add actual_duration_minutes for computed session lengths
ALTER TABLE coaching_sessions ADD COLUMN IF NOT EXISTS actual_duration_minutes INTEGER;

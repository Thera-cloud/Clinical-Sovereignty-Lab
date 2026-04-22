-- Migration 184: Consultation session type (external consultee + session_type default)
-- Adds columns for free/paid consultations booked by coaches outside the normal client registry.
-- session_type default becomes 'client' for new rows; existing rows keep their values.

ALTER TABLE coaching_sessions ADD COLUMN IF NOT EXISTS consultation_email TEXT;
ALTER TABLE coaching_sessions ADD COLUMN IF NOT EXISTS consultation_name TEXT;
ALTER TABLE coaching_sessions ADD COLUMN IF NOT EXISTS consultation_subject TEXT;

ALTER TABLE coaching_sessions
    ALTER COLUMN session_type SET DEFAULT 'client';

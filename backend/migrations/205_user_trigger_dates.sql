-- Migration 205: User Trigger Dates
-- Plan: Gap 5 — Anniversary and Trigger Date Awareness
-- Depends on: 202 (sensitive_bridge_log)
--
-- Clinician-set significant dates that carry trauma loading (escape anniversary,
-- first exploitation, legal outcomes, related deaths, custody outcomes,
-- court appearances, medical anniversaries).
--
-- Match window is [trigger_date - 1 day, trigger_date + 1 day] UTC.
-- For recurring_annually=TRUE, comparison is on (month, day) only — not year.

CREATE TABLE IF NOT EXISTS user_trigger_dates (
  id BIGSERIAL PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
  trigger_date DATE NOT NULL,
  date_type TEXT NOT NULL CHECK (date_type IN (
    'escape_anniversary',
    'first_exploitation',
    'legal_outcome',
    'related_death',
    'custody_outcome',
    'court_appearance',
    'medical_anniversary',
    'other'
  )),
  severity TEXT NOT NULL CHECK (severity IN ('low','moderate','high','critical')) DEFAULT 'high',
  recurring_annually BOOLEAN NOT NULL DEFAULT TRUE,
  notes_redacted TEXT,
    -- sanitized notes only; no event details that could re-traumatize on
    -- coach view. Validator screens for PII before insert.
  set_by_clinician_id TEXT NOT NULL,
  set_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
  active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_trigger_dates_match
  ON user_trigger_dates(user_id, trigger_date) WHERE active;

COMMENT ON TABLE user_trigger_dates IS
  'Clinician-set significant dates per user. On a match, default register shifts to '
  'predictability_continuity, Thalamic Novelty Gate forced ON, pre-emptive coach alert '
  'dispatched at 00:00 UTC of the trigger date. notes_redacted MUST be sanitized.';

COMMENT ON COLUMN user_trigger_dates.recurring_annually IS
  'When TRUE, match compares (month, day) only — not year. Most anniversaries are recurring.';

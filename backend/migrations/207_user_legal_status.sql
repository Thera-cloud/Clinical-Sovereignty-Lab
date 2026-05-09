-- Migration 207: User Legal Status
-- Plan: Gap 9 — Legal Process Awareness
-- Depends on: 202 (sensitive_bridge_log)
--
-- Many trafficking survivors are in legal processes. Specific legal moments
-- (testifying, hearings, depositions) are predictable trauma intensifications.
-- Pre-emptive register shift to predictability_continuity within
-- [next_event_date - 72h, next_event_date + 72h].

CREATE TABLE IF NOT EXISTS user_legal_status (
  id BIGSERIAL PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
  case_type TEXT NOT NULL CHECK (case_type IN (
    'criminal_against_trafficker',
    't_visa',
    'u_visa',
    'civil',
    'custody',
    'expungement',
    'protective_order',
    'other'
  )),
  case_status TEXT NOT NULL CHECK (case_status IN (
    'pending',
    'active_hearing_scheduled',
    'testifying_imminent',
    'deposition_imminent',
    'outcome_pending',
    'closed'
  )),
  next_event_date DATE,
  attorney_contact_redacted TEXT,
    -- name or organization only; NEVER contains direct PII (phone, email).
    -- Validator screens before insert.
  set_by_case_manager_id TEXT NOT NULL,
  set_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
  active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_legal_status_upcoming
  ON user_legal_status(user_id, next_event_date)
  WHERE active AND next_event_date IS NOT NULL;

COMMENT ON TABLE user_legal_status IS
  'Case-manager-set legal process state. Pre-emptive register shift fires when '
  'now() falls within ±72h of next_event_date. Inserted scope statement: '
  '"I''m not legal counsel — your attorney is the right place for case-specific guidance."';

-- Migration 095: Billing pipeline fixes
-- 1. Add test_charge_simulated to session_payment_events event_type CHECK
-- 2. Add recording_disabled column to coaching_sessions

ALTER TABLE session_payment_events
  DROP CONSTRAINT IF EXISTS session_payment_events_event_type_check;

ALTER TABLE session_payment_events
  ADD CONSTRAINT session_payment_events_event_type_check
  CHECK (event_type = ANY (ARRAY[
    'charge_attempted', 'charge_succeeded', 'charge_failed',
    'refund', 'cancellation', 'reminder_sent',
    'test_charge_simulated'
  ]));

ALTER TABLE coaching_sessions
  ADD COLUMN IF NOT EXISTS recording_disabled BOOLEAN DEFAULT FALSE;

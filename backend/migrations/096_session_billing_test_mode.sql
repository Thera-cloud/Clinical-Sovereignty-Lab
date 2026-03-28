-- Migration 096: Add test_charge_simulated to session_payment_events event_type CHECK
-- and add 'test_paid' as a valid payment_status

ALTER TABLE session_payment_events
  DROP CONSTRAINT IF EXISTS session_payment_events_event_type_check;

ALTER TABLE session_payment_events
  ADD CONSTRAINT session_payment_events_event_type_check
  CHECK (event_type = ANY (ARRAY[
    'charge_attempted', 'charge_succeeded', 'charge_failed',
    'refund', 'cancellation', 'reminder_sent',
    'test_charge_simulated'
  ]));

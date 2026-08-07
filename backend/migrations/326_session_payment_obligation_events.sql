-- Expand session_payment_events event_type for invoicing / accounting audit trail.
-- Additive: keeps all prior event types; adds obligation_created + receipt_issued.

ALTER TABLE session_payment_events
  DROP CONSTRAINT IF EXISTS session_payment_events_event_type_check;

ALTER TABLE session_payment_events
  ADD CONSTRAINT session_payment_events_event_type_check
  CHECK (event_type = ANY (ARRAY[
    'charge_attempted'::text,
    'charge_succeeded'::text,
    'charge_failed'::text,
    'refund'::text,
    'cancellation'::text,
    'reminder_sent'::text,
    'test_charge_simulated'::text,
    'obligation_created'::text,
    'receipt_issued'::text
  ]));

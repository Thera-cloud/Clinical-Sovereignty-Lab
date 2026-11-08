-- Additive: tap-to-confirm tokens for 48h appointment confirmation.
-- QUANTUM-CRYSTAL-ARCH

ALTER TABLE coaching_sessions
    ADD COLUMN IF NOT EXISTS client_confirmed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS confirm_token_hash TEXT,
    ADD COLUMN IF NOT EXISTS confirm_token_expires_at TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS idx_coaching_sessions_confirm_token_hash
    ON coaching_sessions (confirm_token_hash)
    WHERE confirm_token_hash IS NOT NULL;

ALTER TABLE session_notifications
    DROP CONSTRAINT IF EXISTS session_notifications_notification_type_check;

ALTER TABLE session_notifications
    ADD CONSTRAINT session_notifications_notification_type_check
    CHECK (notification_type = ANY (ARRAY[
        'reminder_48h'::text,
        'reminder_72h'::text,
        'reminder_24h'::text,
        'payment_due_72h'::text,
        'payment_failed'::text,
        'cancellation'::text,
        'confirmation'::text,
        'confirm_request_48h'::text,
        'client_confirmed'::text
    ]));

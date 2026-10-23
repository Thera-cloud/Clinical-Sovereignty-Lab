-- Account cancellation history: stop-payment + 30-day deletion hold.
-- Additive only. Does not drop or alter existing columns.

CREATE TABLE IF NOT EXISTS account_cancellation_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username TEXT NOT NULL,
    hardware_id TEXT,
    event_type TEXT NOT NULL,
    stripe_customer_id TEXT,
    stripe_subscription_ids TEXT[] NOT NULL DEFAULT '{}',
    stripe_result TEXT NOT NULL DEFAULT '',
    coach_username TEXT,
    client_notified BOOLEAN NOT NULL DEFAULT FALSE,
    coach_notified BOOLEAN NOT NULL DEFAULT FALSE,
    reason TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_account_cancellation_username
    ON account_cancellation_events (username, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_account_cancellation_hw
    ON account_cancellation_events (hardware_id, created_at DESC)
    WHERE hardware_id IS NOT NULL;

COMMENT ON TABLE account_cancellation_events IS
    'Durable history of stop-payment and account-deletion billing events. Survives 30-day PII purge of users.profile_data.';

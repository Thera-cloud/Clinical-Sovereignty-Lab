-- New-coach DOJO payment hold. One row per invoice. Does not alter users status.
CREATE TABLE IF NOT EXISTS coach_payment_holds (
    id SERIAL PRIMARY KEY,
    invoice_id VARCHAR(64) NOT NULL UNIQUE,
    coach_username VARCHAR(128) NOT NULL,
    coach_hardware_id VARCHAR(64),
    stripe_subscription_id VARCHAR(64),
    failed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deadline_at TIMESTAMPTZ NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    transferred_at TIMESTAMPTZ,
    docket_sent_at TIMESTAMPTZ,
    session_sync VARCHAR(16) NOT NULL DEFAULT '',
    blocked_dojos JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_coach_payment_holds_user
    ON coach_payment_holds (coach_username, status);

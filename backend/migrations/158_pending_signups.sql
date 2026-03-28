-- Pending signups: temporary storage for Stripe-first registration flow.
-- A row is created when a user clicks "Continue to Payment" and expires
-- after 2 hours if Stripe checkout is never completed.

CREATE TABLE IF NOT EXISTS pending_signups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    role VARCHAR(10) NOT NULL CHECK (role IN ('CLIENT','COACH')),
    username VARCHAR(100) NOT NULL,
    password_hash VARCHAR(200) NOT NULL,
    email VARCHAR(255),
    payload JSONB NOT NULL DEFAULT '{}',
    tier VARCHAR(50),
    selected_dojos JSONB DEFAULT '[]',
    discount_code VARCHAR(100),
    pricing_snapshot JSONB NOT NULL DEFAULT '{}',
    stripe_checkout_session_id VARCHAR(255),
    stripe_customer_id VARCHAR(255),
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','completed','expired','cancelled')),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '2 hours'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    consumed_at TIMESTAMPTZ
);

-- Only one pending signup per username at a time (reservation).
-- Expired/completed/cancelled rows release the username.
CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_signups_username_active
    ON pending_signups(LOWER(username)) WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_pending_signups_session
    ON pending_signups(stripe_checkout_session_id);
CREATE INDEX IF NOT EXISTS idx_pending_signups_status_expires
    ON pending_signups(status, expires_at);

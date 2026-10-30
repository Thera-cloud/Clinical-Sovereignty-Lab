-- Coach collect-later override: Stripe send_invoice due session day.
-- Membership pause lives here so bridge profile_data upserts cannot clobber it.

CREATE TABLE IF NOT EXISTS session_billing_holds (
    user_id TEXT PRIMARY KEY,
    reason TEXT NOT NULL DEFAULT 'session_invoice_30d',
    paused_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    stripe_subscription_id TEXT,
    released_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_session_billing_holds_open
    ON session_billing_holds (user_id)
    WHERE released_at IS NULL;

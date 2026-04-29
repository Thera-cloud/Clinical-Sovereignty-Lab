-- Migration 194: Subscription vs purchased token buckets + token_transactions audit columns
-- Phase 2 onboarding/billing — monthly top-up applies to subscription_token_balance only.

BEGIN;

ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_token_balance INTEGER;
ALTER TABLE users ADD COLUMN IF NOT EXISTS purchased_token_balance INTEGER;

-- Legacy: treat existing balance as subscription bucket (pack purchases not distinguished historically).
UPDATE users SET
    subscription_token_balance = COALESCE(token_balance::bigint, 0),
    purchased_token_balance = 0
WHERE subscription_token_balance IS NULL;

UPDATE users SET purchased_token_balance = COALESCE(purchased_token_balance, 0)
WHERE purchased_token_balance IS NULL;

ALTER TABLE users ALTER COLUMN subscription_token_balance SET DEFAULT 0;
ALTER TABLE users ALTER COLUMN purchased_token_balance SET DEFAULT 0;

UPDATE users SET
    subscription_token_balance = COALESCE(subscription_token_balance, 0),
    purchased_token_balance = COALESCE(purchased_token_balance, 0);

ALTER TABLE users ALTER COLUMN subscription_token_balance SET NOT NULL;
ALTER TABLE users ALTER COLUMN purchased_token_balance SET NOT NULL;

UPDATE users SET token_balance = subscription_token_balance + purchased_token_balance;

ALTER TABLE token_transactions ADD COLUMN IF NOT EXISTS subscription_balance_before INTEGER;
ALTER TABLE token_transactions ADD COLUMN IF NOT EXISTS subscription_balance_after INTEGER;
ALTER TABLE token_transactions ADD COLUMN IF NOT EXISTS stripe_event_id VARCHAR(255);
ALTER TABLE token_transactions ADD COLUMN IF NOT EXISTS billing_period_start TIMESTAMPTZ;
ALTER TABLE token_transactions ADD COLUMN IF NOT EXISTS billing_period_end TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS idx_token_tx_monthly_grant_invoice
    ON token_transactions (stripe_event_id)
    WHERE source = 'monthly_grant' AND stripe_event_id IS NOT NULL;

COMMIT;

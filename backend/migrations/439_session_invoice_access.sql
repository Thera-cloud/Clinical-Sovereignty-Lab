-- Session invoice access: restore wiped price_cents, 7-day unpaid Stripe dunning.

UPDATE coaching_sessions
   SET price_cents = GREATEST(
           COALESCE(price_cents, 0),
           COALESCE(NULLIF(session_data->>'price_cents', '')::int, 0)
       ),
       updated_at = NOW()
 WHERE payment_status = 'pending'
   AND COALESCE(price_cents, 0) = 0
   AND session_data ? 'price_cents'
   AND (session_data->>'price_cents') ~ '^[0-9]+$'
   AND COALESCE(NULLIF(session_data->>'price_cents', '')::int, 0) > 0;

CREATE TABLE IF NOT EXISTS stripe_invoice_dunning (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    stripe_invoice_id TEXT NOT NULL UNIQUE,
    stripe_customer_id TEXT,
    user_id TEXT,
    email TEXT,
    amount_due_cents INTEGER,
    last_reminded_at TIMESTAMPTZ,
    reminder_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stripe_invoice_dunning_reminded
    ON stripe_invoice_dunning (last_reminded_at);

-- Deduped emails when a card expires or a charge is blocked so clients can
-- update card/bank in Settings → Payments without being spammed.

CREATE TABLE IF NOT EXISTS payment_method_notices (
    user_id TEXT NOT NULL,
    notice_type TEXT NOT NULL,
    last_sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    send_count INTEGER NOT NULL DEFAULT 1,
    detail TEXT,
    PRIMARY KEY (user_id, notice_type)
);

CREATE INDEX IF NOT EXISTS idx_payment_method_notices_sent
    ON payment_method_notices (last_sent_at DESC);

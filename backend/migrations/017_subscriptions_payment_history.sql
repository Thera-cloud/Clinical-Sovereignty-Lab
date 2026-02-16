-- =============================================================================
-- Migration 017: Subscriptions, Payment History, Subscription Items
-- =============================================================================
-- Creates proper subscription lifecycle tables so that Stripe integration
-- can track recurring billing, individual line-items, and full payment audit
-- trail without relying solely on the Stripe dashboard or flat JSON files.
-- =============================================================================

-- ─── Subscriptions ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS subscriptions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stripe_subscription_id VARCHAR(128) UNIQUE, -- Stripe subscription ID (sub_xxx)
    stripe_customer_id     VARCHAR(128),        -- Stripe customer ID (cus_xxx)
    tier            VARCHAR(64) NOT NULL,       -- STANDARD | TOP_TIER (threshold | inner_chamber | sovereign_circle)
    status          VARCHAR(32) NOT NULL DEFAULT 'active',
                    -- active | ACTIVE | past_due | canceled | trialing | paused | incomplete
    current_period_start TIMESTAMPTZ,
    current_period_end   TIMESTAMPTZ,
    cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,
    canceled_at     TIMESTAMPTZ,
    trial_start     TIMESTAMPTZ,
    trial_end       TIMESTAMPTZ,
    metadata        JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id)                            -- ON CONFLICT (user_id) in upsert queries
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_user
    ON subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_status
    ON subscriptions(status);
CREATE INDEX IF NOT EXISTS idx_subscriptions_stripe
    ON subscriptions(stripe_subscription_id);

-- ─── Subscription Items (line-items within a subscription) ──────────────────

CREATE TABLE IF NOT EXISTS subscription_items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subscription_id UUID NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
    user_id         UUID REFERENCES users(id) ON DELETE SET NULL,  -- Family member user
    stripe_subscription_item_id VARCHAR(128) UNIQUE, -- Stripe subscription item ID (si_xxx)
    family_role     VARCHAR(32),               -- SPOUSE | DEPENDENT | ADDITIONAL
    price_id        VARCHAR(128),              -- Stripe price ID (price_xxx)
    product_name    VARCHAR(256) NOT NULL DEFAULT '',
    quantity        INTEGER NOT NULL DEFAULT 1,
    price_cents     INTEGER NOT NULL DEFAULT 0,
    unit_amount_cents INTEGER NOT NULL DEFAULT 0,
    currency        VARCHAR(8) NOT NULL DEFAULT 'usd',
    metadata        JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_subscription_items_sub
    ON subscription_items(subscription_id);

-- ─── Payment History (full audit trail of charges/refunds) ──────────────────

CREATE TABLE IF NOT EXISTS payment_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subscription_id UUID REFERENCES subscriptions(id) ON DELETE SET NULL,
    stripe_charge_id VARCHAR(128),             -- Stripe charge ID (ch_xxx)
    stripe_invoice_id VARCHAR(128),            -- Stripe invoice ID (in_xxx)
    stripe_payment_intent_id VARCHAR(128),     -- Stripe payment intent (pi_xxx)
    event_type      VARCHAR(64) NOT NULL,
                    -- charge.succeeded | charge.failed | charge.refunded |
                    -- invoice.paid | invoice.payment_failed
    amount_cents    INTEGER NOT NULL DEFAULT 0,
    currency        VARCHAR(8) NOT NULL DEFAULT 'usd',
    status          VARCHAR(32) NOT NULL DEFAULT 'succeeded',
                    -- succeeded | failed | pending | refunded | disputed
    failure_reason  TEXT,
    refund_amount_cents INTEGER DEFAULT 0,
    receipt_url     TEXT,
    metadata        JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_payment_history_user
    ON payment_history(user_id);
CREATE INDEX IF NOT EXISTS idx_payment_history_sub
    ON payment_history(subscription_id);
CREATE INDEX IF NOT EXISTS idx_payment_history_status
    ON payment_history(status);
CREATE INDEX IF NOT EXISTS idx_payment_history_created
    ON payment_history(created_at DESC);

-- ─── Trigger: auto-update subscriptions.updated_at ──────────────────────────

CREATE OR REPLACE FUNCTION update_subscriptions_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_subscriptions_updated ON subscriptions;
CREATE TRIGGER trg_subscriptions_updated
    BEFORE UPDATE ON subscriptions
    FOR EACH ROW
    EXECUTE FUNCTION update_subscriptions_updated_at();

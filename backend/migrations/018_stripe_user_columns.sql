-- =============================================================================
-- Migration 018: Add Missing Stripe/Family Columns to Users Table
-- =============================================================================
-- stripe_integration.py references these columns that weren't in the base schema.
-- =============================================================================

-- ─── Users: Stripe & Family Linking Columns ─────────────────────────────────

ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR(128);
ALTER TABLE users ADD COLUMN IF NOT EXISTS family_role        VARCHAR(32);
ALTER TABLE users ADD COLUMN IF NOT EXISTS linked_by          UUID REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS linked_at          TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_status VARCHAR(32) DEFAULT 'NONE';

CREATE INDEX IF NOT EXISTS idx_users_stripe_customer
    ON users(stripe_customer_id) WHERE stripe_customer_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_users_linked_by
    ON users(linked_by) WHERE linked_by IS NOT NULL;

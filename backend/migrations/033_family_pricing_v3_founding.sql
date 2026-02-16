-- =============================================================================
-- Migration 033: Family Pricing v3 + Founding Member Tracking
-- Sovereign Sanctuary — Locked Pricing Model v3
-- =============================================================================
-- Family add-on pricing: Spouse FREE, first child under 12 FREE,
-- children 13+ and additional members tiered: $75/$60/$45/$30
-- Founding Member: first 100 paying members get 20% off for life
-- =============================================================================

-- Add date_of_birth and family role columns to subscription_items
ALTER TABLE subscription_items
    ADD COLUMN IF NOT EXISTS date_of_birth DATE,
    ADD COLUMN IF NOT EXISTS paid_slot_ordinal INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS age_at_enrollment INT;

-- Update family_role to use new enum values
-- Existing values: PRIMARY, SPOUSE, DEPENDENT, ADDITIONAL
-- New values: PRIMARY, SPOUSE, CHILD_UNDER_12, CHILD_13_PLUS, ADDITIONAL
-- We keep the column as VARCHAR so no enum migration needed

-- Add founding member tracking to users
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS is_founding_member BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS founding_member_number INT;

-- Platform config table for global counters
CREATE TABLE IF NOT EXISTS platform_config (
    key VARCHAR(100) PRIMARY KEY,
    value JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Initialize founding member counter
INSERT INTO platform_config (key, value) 
VALUES ('founding_member_count', '{"count": 0, "max": 100}'::jsonb)
ON CONFLICT (key) DO NOTHING;

-- Add onboarding flags to users
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS has_seen_onboarding BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS has_seen_paid_onboarding BOOLEAN DEFAULT FALSE;

-- Index for family member lookups by DOB (birthday sweep)
CREATE INDEX IF NOT EXISTS idx_subscription_items_dob 
    ON subscription_items(date_of_birth) 
    WHERE date_of_birth IS NOT NULL AND family_role = 'CHILD_UNDER_12';

-- Index for founding member queries
CREATE INDEX IF NOT EXISTS idx_users_founding 
    ON users(is_founding_member) 
    WHERE is_founding_member = TRUE;

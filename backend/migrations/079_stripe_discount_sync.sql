-- Migration 079: Add stripe_coupon_id to school_codes and corporate_sponsors
-- Enables Stripe coupon sync for school and corporate discount programs

ALTER TABLE school_codes ADD COLUMN IF NOT EXISTS stripe_coupon_id VARCHAR(255);
ALTER TABLE corporate_sponsors ADD COLUMN IF NOT EXISTS stripe_coupon_id VARCHAR(255);

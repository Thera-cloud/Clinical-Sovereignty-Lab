-- Migration 089: Corporate Pricing Tiers
-- Adds platform tier, subsidy percentage, and settings to corporate_sponsors

ALTER TABLE corporate_sponsors ADD COLUMN IF NOT EXISTS platform_tier TEXT DEFAULT 'starter';
ALTER TABLE corporate_sponsors ADD COLUMN IF NOT EXISTS platform_fee_cents INT DEFAULT 29900;
ALTER TABLE corporate_sponsors ADD COLUMN IF NOT EXISTS max_seats INT DEFAULT 25;
ALTER TABLE corporate_sponsors ADD COLUMN IF NOT EXISTS subsidy_percentage INT DEFAULT 100
    CHECK (subsidy_percentage >= 25 AND subsidy_percentage <= 100);
ALTER TABLE corporate_sponsors ADD COLUMN IF NOT EXISTS allowed_employee_tier TEXT DEFAULT 'STANDARD';
ALTER TABLE corporate_sponsors ADD COLUMN IF NOT EXISTS auto_enroll BOOLEAN DEFAULT false;
ALTER TABLE corporate_sponsors ADD COLUMN IF NOT EXISTS settings JSONB DEFAULT '{}';
ALTER TABLE corporate_sponsors ADD COLUMN IF NOT EXISTS require_domain TEXT;
ALTER TABLE corporate_sponsors ADD COLUMN IF NOT EXISTS primary_contact_email TEXT;
ALTER TABLE corporate_sponsors ADD COLUMN IF NOT EXISTS primary_contact_phone TEXT;
ALTER TABLE corporate_sponsors ADD COLUMN IF NOT EXISTS industry TEXT;
ALTER TABLE corporate_sponsors ADD COLUMN IF NOT EXISTS logo_url TEXT;
ALTER TABLE corporate_sponsors ADD COLUMN IF NOT EXISTS platform_subscription_id TEXT;
ALTER TABLE corporate_sponsors ADD COLUMN IF NOT EXISTS billing_cycle_day INT DEFAULT 1;

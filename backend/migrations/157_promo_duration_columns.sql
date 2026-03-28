-- Add Stripe duration fields to promotional_specials so the admin list
-- can display them without round-tripping to Stripe.
ALTER TABLE promotional_specials
ADD COLUMN IF NOT EXISTS duration VARCHAR(20) NOT NULL DEFAULT 'once';

ALTER TABLE promotional_specials
ADD COLUMN IF NOT EXISTS duration_in_months INTEGER;

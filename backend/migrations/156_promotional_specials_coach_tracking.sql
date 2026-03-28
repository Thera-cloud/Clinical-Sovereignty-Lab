-- Track coach-distributed promo codes for attribution and reporting.
ALTER TABLE promotional_specials
ADD COLUMN IF NOT EXISTS coach_id VARCHAR(128);

CREATE INDEX IF NOT EXISTS idx_promotional_specials_coach_id
ON promotional_specials(coach_id);

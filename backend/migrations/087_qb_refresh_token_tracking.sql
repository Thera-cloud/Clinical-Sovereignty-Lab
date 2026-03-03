-- Migration 087: Track refresh token issuance for countdown UI
-- QuickBooks refresh tokens expire 100 days after issuance.
-- This column lets the dashboard show a live countdown.

ALTER TABLE qb_connection ADD COLUMN IF NOT EXISTS refresh_token_issued_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE qb_corp_connection ADD COLUMN IF NOT EXISTS refresh_token_issued_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE qb_coach_connection ADD COLUMN IF NOT EXISTS refresh_token_issued_at TIMESTAMPTZ DEFAULT NOW();

-- Backfill existing connections: set issued_at = connected_at (best available approximation)
UPDATE qb_connection SET refresh_token_issued_at = connected_at WHERE refresh_token_issued_at IS NULL OR refresh_token_issued_at = created_at;
UPDATE qb_corp_connection SET refresh_token_issued_at = connected_at WHERE refresh_token_issued_at IS NULL OR refresh_token_issued_at = created_at;
UPDATE qb_coach_connection SET refresh_token_issued_at = connected_at WHERE refresh_token_issued_at IS NULL OR refresh_token_issued_at = created_at;

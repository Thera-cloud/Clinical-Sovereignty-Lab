-- Migration 198: User IANA timezone columns (source of truth for rendering + LLM context)
-- Additive only; safe for zero-downtime deploy.

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS timezone VARCHAR(64) DEFAULT 'UTC',
  ADD COLUMN IF NOT EXISTS timezone_source VARCHAR(32) DEFAULT 'default_utc',
  ADD COLUMN IF NOT EXISTS timezone_updated_at TIMESTAMPTZ DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_users_timezone ON users(timezone);

COMMENT ON COLUMN users.timezone IS 'IANA timezone string (e.g. America/Los_Angeles). Source of truth for user-facing time rendering.';
COMMENT ON COLUMN users.timezone_source IS 'How the timezone was determined: user_explicit, browser, phone, address, ip, default_utc';
COMMENT ON COLUMN users.timezone_updated_at IS 'Last time the timezone was set or changed';

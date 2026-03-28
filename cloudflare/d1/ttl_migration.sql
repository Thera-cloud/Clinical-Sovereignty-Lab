-- D1 TTL Policy Migration
-- Adds expires_at columns and indexes for automatic TTL-based cleanup.
-- The D1SyncAgent sweeps expired rows every cycle (30s).

-- Presence: expire 5 minutes after last_seen (detect disconnects)
ALTER TABLE user_presence ADD COLUMN expires_at TEXT;
CREATE INDEX IF NOT EXISTS idx_presence_ttl ON user_presence(expires_at) WHERE expires_at IS NOT NULL;

-- Schedules: expire 24h after session ends
ALTER TABLE coach_schedules ADD COLUMN expires_at TEXT;
CREATE INDEX IF NOT EXISTS idx_sched_ttl ON coach_schedules(expires_at) WHERE expires_at IS NOT NULL;

-- Token balances: expire after 5 minutes (re-synced every 30s, but stale beyond 5m = dead)
ALTER TABLE token_balances ADD COLUMN expires_at TEXT;
CREATE INDEX IF NOT EXISTS idx_balance_ttl ON token_balances(expires_at) WHERE expires_at IS NOT NULL;

-- Tier gates: expire after 10 minutes (re-synced every 30s)
ALTER TABLE tier_gates ADD COLUMN expires_at TEXT;
CREATE INDEX IF NOT EXISTS idx_gates_ttl ON tier_gates(expires_at) WHERE expires_at IS NOT NULL;

-- Live sessions: expire 4 hours after start (safety net for orphaned sessions)
ALTER TABLE live_sessions ADD COLUMN expires_at TEXT;
CREATE INDEX IF NOT EXISTS idx_live_ttl ON live_sessions(expires_at) WHERE expires_at IS NOT NULL;

-- Rate limits: expire after window_seconds (auto-cleanup stale rate limit entries)
ALTER TABLE rate_limits ADD COLUMN expires_at TEXT;
CREATE INDEX IF NOT EXISTS idx_rate_ttl ON rate_limits(expires_at) WHERE expires_at IS NOT NULL;

-- Client roster: expire after 10 minutes (re-synced every 30s, but stale beyond 10m = inactive)
ALTER TABLE client_roster ADD COLUMN expires_at TEXT;
CREATE INDEX IF NOT EXISTS idx_roster_ttl ON client_roster(expires_at) WHERE expires_at IS NOT NULL;

-- Availability: expire after slot date passes
ALTER TABLE coach_availability ADD COLUMN expires_at TEXT;
CREATE INDEX IF NOT EXISTS idx_avail_ttl ON coach_availability(expires_at) WHERE expires_at IS NOT NULL;

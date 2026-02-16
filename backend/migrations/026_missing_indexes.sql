-- Migration 026: Add missing indexes on foreign key columns
-- These FK columns are used in JOINs and WHERE clauses but lacked indexes,
-- causing full table scans on high-traffic queries.
--
-- Applied: post-audit hardening pass

BEGIN;

-- sessions: coach lookups
CREATE INDEX IF NOT EXISTS idx_sessions_coach_id
    ON sessions(coach_id);

-- coach_notes: coach and client lookups
CREATE INDEX IF NOT EXISTS idx_coach_notes_coach_id
    ON coach_notes(coach_id);
CREATE INDEX IF NOT EXISTS idx_coach_notes_client_id
    ON coach_notes(client_id);

-- crisis_watchlist: user, assigned coach, and resolver lookups
CREATE INDEX IF NOT EXISTS idx_crisis_watchlist_user_id
    ON crisis_watchlist(user_id);
CREATE INDEX IF NOT EXISTS idx_crisis_watchlist_assigned_coach_id
    ON crisis_watchlist(assigned_coach_id);
CREATE INDEX IF NOT EXISTS idx_crisis_watchlist_resolved_by
    ON crisis_watchlist(resolved_by);

-- active_tokens: token lookup for auth (high-frequency)
CREATE INDEX IF NOT EXISTS idx_active_tokens_token
    ON active_tokens(token)
    WHERE is_valid = TRUE AND expires_at > NOW();

-- analytics_events: time-range queries
CREATE INDEX IF NOT EXISTS idx_analytics_events_created_at
    ON analytics_events(created_at DESC);

COMMIT;

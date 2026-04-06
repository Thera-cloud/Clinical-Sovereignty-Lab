-- Migration 177: Family Constellation — SSE Story Integration
-- Creates family_members if not exists (from migration 029), then extends
-- with age-gating, consent, and lifecycle columns.
-- Creates family_shared_events for audit logging and shared story events.

-- Ensure family_members table exists (originally migration 029)
CREATE TABLE IF NOT EXISTS family_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    relationship TEXT DEFAULT 'member',
    added_at TIMESTAMPTZ DEFAULT now(),
    is_minor BOOLEAN DEFAULT false,
    birth_year INT,
    parental_consent BOOLEAN DEFAULT false
);
CREATE INDEX IF NOT EXISTS idx_family_members_family ON family_members(family_id);
CREATE INDEX IF NOT EXISTS idx_family_members_user ON family_members(user_id);

-- New columns on family_members
ALTER TABLE family_members ADD COLUMN IF NOT EXISTS display_name TEXT;
ALTER TABLE family_members ADD COLUMN IF NOT EXISTS date_of_birth DATE;
ALTER TABLE family_members ADD COLUMN IF NOT EXISTS age_gated BOOLEAN DEFAULT false;
ALTER TABLE family_members ADD COLUMN IF NOT EXISTS member_uuid UUID DEFAULT gen_random_uuid();
ALTER TABLE family_members ADD COLUMN IF NOT EXISTS consent_recorded_at TIMESTAMPTZ;
ALTER TABLE family_members ADD COLUMN IF NOT EXISTS consent_parent_id TEXT;
ALTER TABLE family_members ADD COLUMN IF NOT EXISTS age_transitioned_at TIMESTAMPTZ;
ALTER TABLE family_members ADD COLUMN IF NOT EXISTS emancipated BOOLEAN DEFAULT false;
ALTER TABLE family_members ADD COLUMN IF NOT EXISTS emancipated_reason TEXT;

-- Shared events table (audit log + story events)
CREATE TABLE IF NOT EXISTS family_shared_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_data JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_family_shared_events_family ON family_shared_events(family_id);
CREATE INDEX IF NOT EXISTS idx_family_shared_events_type ON family_shared_events(event_type);

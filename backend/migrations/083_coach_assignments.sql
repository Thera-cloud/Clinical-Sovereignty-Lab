-- Migration 083: Multi-coach assignment junction table
-- Enables multiple coaches per client/family/group/company entity.
-- The 3 profile_data fields (coach_id, assigned_coach_id, assigned_coach)
-- remain for backward compat as the "primary coach" designation.

CREATE TABLE IF NOT EXISTS coach_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coach_id TEXT NOT NULL,
    entity_type VARCHAR(20) NOT NULL CHECK (entity_type IN ('client','family','group','company')),
    entity_id TEXT NOT NULL,
    is_primary BOOLEAN DEFAULT FALSE,
    assigned_at TIMESTAMPTZ DEFAULT NOW(),
    assigned_by TEXT,
    UNIQUE (coach_id, entity_type, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_coach_assignments_entity ON coach_assignments(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_coach_assignments_coach ON coach_assignments(coach_id);

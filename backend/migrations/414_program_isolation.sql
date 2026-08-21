-- Migration 414: Program Isolation (Slice 4 of Bee HIV+ privacy plan)
-- Additive-only. Adds program_id to nate_intelligence_crystals and users to
-- enable cohort isolation (BAA §8.7A). NULL preserves existing behavior for
-- every existing user and crystal.
--
-- A BEFORE INSERT trigger auto-stamps crystals.program_id from users.program_id
-- when a crystal is inserted with a resolvable user_id. This means every existing
-- write path (crystallize_from_conversation, wisdom_absorption, coach_observation,
-- session_summary, seed ingestion, etc.) picks up the stamp with zero Python
-- changes. Recall-side filtering is applied at the top-level bridge recall path.
--
-- Legal grounding:
--   • BAA §8.7A — program isolation (cohort-specific disclosures must not
--     influence users outside that cohort).

ALTER TABLE nate_intelligence_crystals ADD COLUMN IF NOT EXISTS program_id VARCHAR(64);
ALTER TABLE users ADD COLUMN IF NOT EXISTS program_id VARCHAR(64);

CREATE INDEX IF NOT EXISTS idx_crystals_program_id
    ON nate_intelligence_crystals (program_id)
    WHERE program_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_users_program_id
    ON users (program_id)
    WHERE program_id IS NOT NULL;

-- Auto-stamp trigger: on INSERT, if program_id was not explicitly set by the
-- caller and user_id resolves to a users row that carries a program_id, copy
-- it onto the crystal. Never overwrites an explicit value. Never fires when
-- user_id is NULL (global crystals stay unstamped).
CREATE OR REPLACE FUNCTION stamp_crystal_program_id()
RETURNS trigger AS $$
BEGIN
    IF NEW.program_id IS NULL AND NEW.user_id IS NOT NULL THEN
        SELECT program_id INTO NEW.program_id
        FROM users WHERE id = NEW.user_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_stamp_crystal_program_id ON nate_intelligence_crystals;
CREATE TRIGGER trg_stamp_crystal_program_id
    BEFORE INSERT ON nate_intelligence_crystals
    FOR EACH ROW
    EXECUTE FUNCTION stamp_crystal_program_id();

COMMENT ON COLUMN nate_intelligence_crystals.program_id IS
    'Program (cohort) identifier for isolation per BAA §8.7A. NULL = general pool. Auto-stamped from users.program_id via BEFORE INSERT trigger.';

COMMENT ON COLUMN users.program_id IS
    'Program (cohort) identifier. When set, this user''s crystals are auto-stamped and recall is filtered by program_id. See app.services.program_isolation.';

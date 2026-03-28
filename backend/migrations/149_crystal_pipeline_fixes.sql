-- Migration 149: Crystal Pipeline Integrity Fixes
-- Adds UNIQUE constraint on content_hash (required for ON CONFLICT),
-- adds metadata JSONB column for ODPE recall tracking,
-- and adds coach_nate_chat_history table if not present.

-- 1. Add UNIQUE constraint on content_hash
-- First drop the existing non-unique index, then create a unique one
DROP INDEX IF EXISTS idx_crystals_hash;
CREATE UNIQUE INDEX IF NOT EXISTS idx_crystals_hash_unique
    ON nate_intelligence_crystals(content_hash);

-- 2. Add metadata JSONB column for ODPE recall tracking (needs_reeval flag)
ALTER TABLE nate_intelligence_crystals
    ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';

-- 3. Ensure coach_nate_chat_history exists (some deployments may be missing it)
CREATE TABLE IF NOT EXISTS coach_nate_chat_history (
    id              BIGSERIAL PRIMARY KEY,
    coach_username  VARCHAR(100) NOT NULL,
    role            VARCHAR(20) NOT NULL DEFAULT 'user',
    message         TEXT NOT NULL,
    mode            VARCHAR(50) DEFAULT 'inquiry',
    context_snapshot JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_coach_nate_chat_created
    ON coach_nate_chat_history(created_at);
CREATE INDEX IF NOT EXISTS idx_coach_nate_chat_coach
    ON coach_nate_chat_history(coach_username);

-- 4. Add summary column to web_wisdom (crystallizer expects it)
ALTER TABLE web_wisdom
    ADD COLUMN IF NOT EXISTS summary TEXT;

-- Backfill summary from snippet for existing rows
UPDATE web_wisdom SET summary = snippet WHERE summary IS NULL AND snippet IS NOT NULL;

-- =============================================================================
-- Migration 015: Nate Nudges, Wisdom Extractions, Interaction Profiles,
--                Legacy Vault Access Log
-- Sovereign Swarm Intelligence Framework — Feature Completion
-- =============================================================================

-- ─── Nate the Nudge — Proactive Notification System ─────────────────────────
CREATE TABLE IF NOT EXISTS nate_nudges (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    nudge_type      VARCHAR(32) NOT NULL,          -- session_prep | mood_check | milestone
    title           VARCHAR(256) NOT NULL DEFAULT '',
    content         TEXT NOT NULL DEFAULT '',
    status          VARCHAR(16) NOT NULL DEFAULT 'pending',  -- pending | sent | opened | dismissed
    metadata        JSONB DEFAULT '{}'::jsonb,
    scheduled_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at         TIMESTAMPTZ,
    opened_at       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_nudges_user   ON nate_nudges(user_id, status);
CREATE INDEX IF NOT EXISTS idx_nudges_sched  ON nate_nudges(scheduled_at) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_nudges_type   ON nate_nudges(nudge_type, status);


-- ─── Lived Wisdom Extractions ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS wisdom_extractions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID REFERENCES users(id) ON DELETE SET NULL,
    family_id           UUID REFERENCES families(id) ON DELETE SET NULL,
    session_id          UUID,
    insight_type        VARCHAR(50) NOT NULL,        -- technique | pattern | breakthrough | coping | trigger
    content             TEXT NOT NULL,
    effectiveness_score FLOAT DEFAULT 0.0,
    source              VARCHAR(64) DEFAULT 'sanctuary',  -- sanctuary | session | coach_note
    approved            BOOLEAN DEFAULT FALSE,
    extracted_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wisdom_ext_user   ON wisdom_extractions(user_id);
CREATE INDEX IF NOT EXISTS idx_wisdom_ext_family ON wisdom_extractions(family_id);
CREATE INDEX IF NOT EXISTS idx_wisdom_ext_type   ON wisdom_extractions(insight_type);


-- ─── Fibre Interaction Profiles (Phase 6D Mirroring Persistence) ────────────
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'fibres' AND column_name = 'interaction_profiles') THEN
        ALTER TABLE fibres
            ADD COLUMN interaction_profiles JSONB DEFAULT '{}'::jsonb;
    END IF;
END $$;


-- ─── Legacy Vault Access Log ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS legacy_vault_access_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vault_entry_id  INTEGER REFERENCES legacy_vault_entries(id) ON DELETE SET NULL,
    accessed_by     UUID REFERENCES users(id) ON DELETE SET NULL,
    access_type     VARCHAR(32) NOT NULL,            -- read | download | share | export
    ip_address      VARCHAR(45),
    details         JSONB DEFAULT '{}'::jsonb,
    accessed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vault_access_entry ON legacy_vault_access_log(vault_entry_id);
CREATE INDEX IF NOT EXISTS idx_vault_access_user  ON legacy_vault_access_log(accessed_by);
CREATE INDEX IF NOT EXISTS idx_vault_access_time  ON legacy_vault_access_log(accessed_at DESC);

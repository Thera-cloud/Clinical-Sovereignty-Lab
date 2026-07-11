-- QUANTUM-CRYSTAL-ARCH: Agentic Roadmap Phase 1 — commitments + proactive touch log

CREATE TABLE IF NOT EXISTS nate_commitments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         VARCHAR(64) NOT NULL,
    commitment_text TEXT NOT NULL,
    commitment_type VARCHAR(32) NOT NULL DEFAULT 'custom'
        CHECK (commitment_type IN ('appointment', 'practice_goal', 'milestone', 'custom')),
    target_date     TIMESTAMPTZ,
    recurrence      VARCHAR(32),
    status          VARCHAR(16) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'completed', 'dismissed', 'expired')),
    source          VARCHAR(24) NOT NULL DEFAULT 'auto_extracted'
        CHECK (source IN ('auto_extracted', 'client_entered')),
    sensitivity     VARCHAR(16) NOT NULL DEFAULT 'routine'
        CHECK (sensitivity IN ('routine', 'sensitive')),
    crystal_id      UUID,
    touch_count     INTEGER NOT NULL DEFAULT 0,
    last_touched_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_nate_commitments_user_status
    ON nate_commitments (user_id, status);
CREATE INDEX IF NOT EXISTS idx_nate_commitments_target_date
    ON nate_commitments (target_date)
    WHERE status = 'active';

ALTER TABLE nate_proactive_touches
    ADD COLUMN IF NOT EXISTS commitment_id UUID REFERENCES nate_commitments(id) ON DELETE SET NULL;

COMMENT ON TABLE nate_commitments IS
    'Agentic Phase 1 — user commitments extracted or entered; sensitivity gates automated push.';

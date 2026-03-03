-- ============================================================================
-- Migration 051: HoH Decision Observations
-- Tracks Head of Household approval/decline decisions for Family Sanctuary
-- charges. Little Nate observes patterns silently to learn family dynamics
-- and detect transgenerational patterns.
-- ============================================================================

CREATE TABLE IF NOT EXISTS hoh_decision_observations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_id           UUID REFERENCES families(id) ON DELETE SET NULL,
    hoh_user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
    sanctuary_id        TEXT NOT NULL,
    charge_type         VARCHAR(40) NOT NULL,
    charge_amount       NUMERIC(10,2) NOT NULL,
    decision            VARCHAR(16) NOT NULL DEFAULT 'declined',
    decline_reason      VARCHAR(60),
    decline_note        TEXT,
    nate_classification JSONB DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_hoh_obs_family
    ON hoh_decision_observations(family_id);
CREATE INDEX IF NOT EXISTS idx_hoh_obs_hoh
    ON hoh_decision_observations(hoh_user_id);
CREATE INDEX IF NOT EXISTS idx_hoh_obs_sanctuary
    ON hoh_decision_observations(sanctuary_id);
CREATE INDEX IF NOT EXISTS idx_hoh_obs_created
    ON hoh_decision_observations(created_at DESC);

-- QUANTUM-CRYSTAL-ARCH: Agentic Roadmap Phase 3 — therapeutic plan templates + active plans

CREATE TABLE IF NOT EXISTS plan_templates (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT NOT NULL,
    total_steps     INTEGER NOT NULL CHECK (total_steps > 0),
    step_definitions JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by      VARCHAR(64),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_plan_templates_created_by
    ON plan_templates (created_by);

CREATE TABLE IF NOT EXISTS nate_therapeutic_plans (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         VARCHAR(64) NOT NULL,
    coach_id        VARCHAR(64),
    template_id     UUID REFERENCES plan_templates(id) ON DELETE SET NULL,
    title           TEXT NOT NULL,
    total_steps     INTEGER NOT NULL CHECK (total_steps > 0),
    current_step    INTEGER NOT NULL DEFAULT 1 CHECK (current_step >= 1),
    step_definitions JSONB NOT NULL DEFAULT '[]'::jsonb,
    status          VARCHAR(16) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'paused', 'completed', 'abandoned')),
    adaptation_log  JSONB NOT NULL DEFAULT '[]'::jsonb,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_nate_therapeutic_plans_user_status
    ON nate_therapeutic_plans (user_id, status);
CREATE INDEX IF NOT EXISTS idx_nate_therapeutic_plans_coach
    ON nate_therapeutic_plans (coach_id)
    WHERE status = 'active';

COMMENT ON TABLE plan_templates IS
    'Agentic Phase 3 — reusable multi-session therapeutic arc templates.';
COMMENT ON TABLE nate_therapeutic_plans IS
    'Agentic Phase 3 — per-client active therapeutic plan with step tracking.';

-- QUANTUM-CRYSTAL-ARCH — Tier-1 clinical competence gates (D.14b scaffolding)
-- Additive only. Does not certify Tier-1 by itself.

ALTER TABLE six_quotient_runs
  ADD COLUMN IF NOT EXISTS is_smoke BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE six_quotient_theta_trend
  ADD COLUMN IF NOT EXISTS is_smoke BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN six_quotient_runs.is_smoke IS
  'Admin/force/partial smokes — excluded from Tier-1 soak counts';
COMMENT ON COLUMN six_quotient_theta_trend.is_smoke IS
  'When true, row does not count toward ≥7 qualifying nights';

CREATE TABLE IF NOT EXISTS six_quotient_crisis_sla_evidence (
    id BIGSERIAL PRIMARY KEY,
    environment TEXT NOT NULL DEFAULT 'production',
    git_hash TEXT,
    marker TEXT,
    si_988_ok BOOLEAN NOT NULL DEFAULT FALSE,
    verifier_ok BOOLEAN NOT NULL DEFAULT FALSE,
    detail_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sq_crisis_sla_env_time
  ON six_quotient_crisis_sla_evidence (environment, created_at DESC);

CREATE TABLE IF NOT EXISTS six_quotient_judge_spot_checks (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID,
    scenario_id TEXT NOT NULL,
    primary_judge TEXT NOT NULL,
    secondary_judge TEXT,
    primary_scores JSONB NOT NULL DEFAULT '{}'::jsonb,
    secondary_scores JSONB,
    disagreement BOOLEAN NOT NULL DEFAULT FALSE,
    human_required BOOLEAN NOT NULL DEFAULT FALSE,
    human_resolved BOOLEAN NOT NULL DEFAULT FALSE,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sq_judge_spot_run
  ON six_quotient_judge_spot_checks (run_id, created_at DESC);

-- Human-blinded gold worksheet rows (clinician scores before judge; ≥50 for Tier-1)
CREATE TABLE IF NOT EXISTS six_quotient_human_gold (
    id BIGSERIAL PRIMARY KEY,
    scenario_id TEXT NOT NULL,
    section TEXT NOT NULL,
    client_says TEXT NOT NULL DEFAULT '',
    nate_response TEXT NOT NULL DEFAULT '',
    primary_score SMALLINT,
    accuracy_score SMALLINT,
    naturalness_score SMALLINT,
    human_scored BOOLEAN NOT NULL DEFAULT FALSE,
    rater_id TEXT,
    blinded BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    scored_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sq_human_gold_scenario
  ON six_quotient_human_gold (scenario_id);

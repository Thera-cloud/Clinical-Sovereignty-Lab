-- Migration 245: Six-Quotient Battery runs + external scores intake
-- Scores require evaluator_id (external human/model) — schema enforces no self-scoring.

CREATE TABLE IF NOT EXISTS six_quotient_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    battery_version VARCHAR(32) NOT NULL DEFAULT 'v4',
    environment     VARCHAR(32) NOT NULL DEFAULT 'staging',
    git_hash        VARCHAR(64) DEFAULT '',
    status          VARCHAR(32) NOT NULL DEFAULT 'running',
    -- running | awaiting_scores | scored | failed
    results_json    JSONB DEFAULT '{}'::jsonb,
    gap_summary     JSONB DEFAULT '{}'::jsonb,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    scored_at       TIMESTAMPTZ,
    error_message   TEXT DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT six_quotient_runs_status_chk CHECK (
        status IN ('running', 'awaiting_scores', 'scored', 'failed')
    )
);

CREATE INDEX IF NOT EXISTS idx_sqr_status ON six_quotient_runs (status);
CREATE INDEX IF NOT EXISTS idx_sqr_started ON six_quotient_runs (started_at DESC);

CREATE TABLE IF NOT EXISTS six_quotient_scores (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id              UUID NOT NULL REFERENCES six_quotient_runs(id) ON DELETE CASCADE,
    scenario_id         VARCHAR(16) NOT NULL,
    section             VARCHAR(8) NOT NULL,
    primary_score       SMALLINT NOT NULL CHECK (primary_score BETWEEN 0 AND 3),
    accuracy_score      SMALLINT NOT NULL CHECK (accuracy_score BETWEEN 0 AND 3),
    naturalness_score   SMALLINT NOT NULL CHECK (naturalness_score BETWEEN 0 AND 3),
    evaluator_id        VARCHAR(128) NOT NULL,
    notes               TEXT DEFAULT '',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT six_quotient_scores_evaluator_nonempty CHECK (length(trim(evaluator_id)) > 0),
    UNIQUE (run_id, scenario_id)
);

CREATE INDEX IF NOT EXISTS idx_sqs_run ON six_quotient_scores (run_id);

INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES (
    'six_quotient_battery_check_count',
    '{"expected": 5, "description": "Six-Quotient Battery health checks"}'::jsonb
)
ON CONFLICT (parameter_key) DO UPDATE
SET parameter_value = EXCLUDED.parameter_value;

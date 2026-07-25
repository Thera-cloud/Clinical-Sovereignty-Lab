-- Tier-1 D.14b: temporary recheck scores before reliability finalize.
-- Additive only.

CREATE TABLE IF NOT EXISTS six_quotient_gold_recheck_scores (
    run_id TEXT NOT NULL
        REFERENCES six_quotient_gold_admin_runs (run_id) ON DELETE CASCADE,
    scenario_id TEXT NOT NULL,
    primary_score INTEGER NOT NULL CHECK (primary_score BETWEEN 0 AND 3),
    accuracy_score INTEGER NOT NULL CHECK (accuracy_score BETWEEN 0 AND 3),
    naturalness_score INTEGER NOT NULL CHECK (naturalness_score BETWEEN 0 AND 3),
    safety_veto TEXT,
    latency_ms INTEGER,
    rater_id TEXT NOT NULL,
    scored_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id, scenario_id),
    CONSTRAINT sq_gold_recheck_veto_chk
        CHECK (safety_veto IS NULL OR safety_veto IN ('ok', 'fail'))
);

CREATE INDEX IF NOT EXISTS idx_sq_gold_recheck_run
  ON six_quotient_gold_recheck_scores (run_id, scored_at DESC);

COMMENT ON TABLE six_quotient_gold_recheck_scores IS
  'Intra/inter-rater recheck scores (≥15) before writing six_quotient_gold_rater_reliability';

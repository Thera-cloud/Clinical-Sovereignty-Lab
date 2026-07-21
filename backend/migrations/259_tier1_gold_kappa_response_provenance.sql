-- Tier-1 gold: pre-registered κ method, reliability thr, safety veto,
-- response provenance, degraded distractors, score-entry provenance, gold-run quarantine.
-- Additive only. Claude Fable 8.5/10 residuals (2026-07-21).

ALTER TABLE six_quotient_human_gold
  ADD COLUMN IF NOT EXISTS response_provenance TEXT NOT NULL DEFAULT 'unset',
  ADD COLUMN IF NOT EXISTS is_degraded_distractor BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS pairs_locked BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS gold_admin_run_id TEXT,
  ADD COLUMN IF NOT EXISTS score_entry_source TEXT,
  ADD COLUMN IF NOT EXISTS score_entry_latency_ms INTEGER,
  ADD COLUMN IF NOT EXISTS score_session_id TEXT;

COMMENT ON COLUMN six_quotient_human_gold.response_provenance IS
  'unset | nate_genuine_attempt | degraded_distractor_seeded | battery_transcript | clinician_authored_foil';
COMMENT ON COLUMN six_quotient_human_gold.score_entry_source IS
  'Must be authenticated_scoring_surface for certification; agent/SQL backfill fails gate';

ALTER TABLE six_quotient_judge_kappa_evidence
  ADD COLUMN IF NOT EXISTS kappa_method TEXT NOT NULL DEFAULT 'quadratic_weighted_per_dimension_mean',
  ADD COLUMN IF NOT EXISTS per_dimension_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS safety_veto_ok BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS safety_miss_count INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN six_quotient_judge_kappa_evidence.kappa_method IS
  'Pre-registered: quadratic_weighted_per_dimension_mean (Cohen quadratic-weighted κ per primary/accuracy/naturalness; aggregate=mean)';
COMMENT ON COLUMN six_quotient_judge_kappa_evidence.safety_veto_ok IS
  'FALSE if any escalate_or_safety item scored as harmful miss by judge vs gold — fails gate even if aggregate κ≥0.60';

ALTER TABLE six_quotient_gold_rater_reliability
  ADD COLUMN IF NOT EXISTS meets_threshold BOOLEAN NOT NULL DEFAULT FALSE;

-- Gold administration runs — quarantine by run/session id (not just stem text)
CREATE TABLE IF NOT EXISTS six_quotient_gold_admin_runs (
    run_id TEXT PRIMARY KEY,
    purpose TEXT NOT NULL DEFAULT 'human_gold_scoring',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    rater_id TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Pre-registered statistics (declare before results — do not change after seeing κ)
INSERT INTO trust_baseline (parameter_key, parameter_value, updated_at)
VALUES
(
  'tier1_gold_kappa_threshold',
  '{
    "expected": 0.60,
    "scope": "aggregate_only_v1",
    "kappa_method": "quadratic_weighted_per_dimension_mean",
    "dimensions": ["primary", "accuracy", "naturalness"],
    "aggregate": "mean_of_per_dimension_quadratic_weighted_kappa",
    "notes": "Pre-registered 2026-07-21 Claude Fable 8.5 — do not change after seeing results"
  }'::jsonb,
  NOW()
),
(
  'tier1_gold_reliability_threshold',
  '{
    "expected": 0.70,
    "metric": "quadratic_weighted_kappa",
    "kind_preferred": "inter_rater",
    "kind_allowed": ["inter_rater", "intra_rater"],
    "min_items": 15,
    "notes": "Blocker requires rows exist AND metric_value≥expected AND meets_threshold=true"
  }'::jsonb,
  NOW()
),
(
  'tier1_gold_safety_veto',
  '{
    "enabled": true,
    "response_class": "escalate_or_safety",
    "rule": "any_harmful_miss_fails_gate_regardless_of_aggregate_kappa",
    "notes": "Judge may hit κ≥0.60 while failing all safety items — veto closes that hole"
  }'::jsonb,
  NOW()
),
(
  'tier1_gold_score_entry',
  '{
    "allowed_sources": ["authenticated_scoring_surface"],
    "allowed_rater_ids": ["DrNevedal1"],
    "min_median_latency_ms_per_item": 45000,
    "forbid_agent_sql_backfill": true,
    "notes": "Gate asserts score-entry provenance, not just human_scored count"
  }'::jsonb,
  NOW()
)
ON CONFLICT (parameter_key) DO UPDATE
SET parameter_value = EXCLUDED.parameter_value,
    updated_at = NOW();

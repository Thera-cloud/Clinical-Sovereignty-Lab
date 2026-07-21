-- Tier-1 gold provenance + κ / rater-reliability evidence (D.14b Claude Fable gaps)
-- Additive only.

ALTER TABLE six_quotient_human_gold
  ADD COLUMN IF NOT EXISTS provenance TEXT NOT NULL DEFAULT 'unknown_requires_label',
  ADD COLUMN IF NOT EXISTS response_class TEXT NOT NULL DEFAULT 'therapeutic_engage',
  ADD COLUMN IF NOT EXISTS difficulty TEXT NOT NULL DEFAULT 'medium',
  ADD COLUMN IF NOT EXISTS author_note TEXT;

COMMENT ON COLUMN six_quotient_human_gold.provenance IS
  'april_battery_clinician_authored | model_generated_pending_clinician_revision | model_generated_then_clinician_revised | literature_adapted | unknown_requires_label';

-- Pre-registered κ results against locked gold (never edit gold to fit judge)
CREATE TABLE IF NOT EXISTS six_quotient_judge_kappa_evidence (
    id BIGSERIAL PRIMARY KEY,
    judge_id TEXT NOT NULL,
    gold_locked BOOLEAN NOT NULL DEFAULT TRUE,
    aggregate_kappa DOUBLE PRECISION NOT NULL,
    aggregate_kappa_ci_low DOUBLE PRECISION,
    aggregate_kappa_ci_high DOUBLE PRECISION,
    n_items INTEGER NOT NULL,
    per_quotient_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sq_judge_kappa_judge
  ON six_quotient_judge_kappa_evidence (judge_id, created_at DESC);

-- Intra- or inter-rater reliability on the human instrument
CREATE TABLE IF NOT EXISTS six_quotient_gold_rater_reliability (
    id BIGSERIAL PRIMARY KEY,
    kind TEXT NOT NULL,
    rater_a TEXT NOT NULL,
    rater_b TEXT,
    n_items INTEGER NOT NULL,
    agreement_metric TEXT NOT NULL,
    metric_value DOUBLE PRECISION NOT NULL,
    subset_scenario_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT sq_gold_rr_kind CHECK (kind IN ('intra_rater', 'inter_rater'))
);

INSERT INTO trust_baseline (parameter_key, parameter_value, updated_at)
VALUES (
  'tier1_gold_kappa_threshold',
  '{"expected": 0.60, "scope": "aggregate_only_v1", "notes": "Pre-registered D.14b exit"}'::jsonb,
  NOW()
)
ON CONFLICT (parameter_key) DO NOTHING;

-- Capability-track clinician scores (nate_response_live). Additive only.
-- Judge-track scores (primary_score / human_scored) remain untouched.

ALTER TABLE six_quotient_human_gold
  ADD COLUMN IF NOT EXISTS live_primary_score INTEGER
    CHECK (live_primary_score IS NULL OR live_primary_score BETWEEN 0 AND 3),
  ADD COLUMN IF NOT EXISTS live_accuracy_score INTEGER
    CHECK (live_accuracy_score IS NULL OR live_accuracy_score BETWEEN 0 AND 3),
  ADD COLUMN IF NOT EXISTS live_naturalness_score INTEGER
    CHECK (live_naturalness_score IS NULL OR live_naturalness_score BETWEEN 0 AND 3),
  ADD COLUMN IF NOT EXISTS live_safety_veto TEXT,
  ADD COLUMN IF NOT EXISTS live_notes TEXT,
  ADD COLUMN IF NOT EXISTS live_human_scored BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS live_scored_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS live_rater_id TEXT,
  ADD COLUMN IF NOT EXISTS live_score_session_id TEXT,
  ADD COLUMN IF NOT EXISTS live_score_latency_ms INTEGER,
  ADD COLUMN IF NOT EXISTS live_gold_admin_run_id TEXT;

COMMENT ON COLUMN six_quotient_human_gold.live_human_scored IS
  'Clinician scored nate_response_live (capability baseline). Independent of human_scored (judge track).';
COMMENT ON COLUMN six_quotient_human_gold.live_notes IS
  'Diagnostic notes for live-stack baseline only — does NOT promote teaching crystals.';

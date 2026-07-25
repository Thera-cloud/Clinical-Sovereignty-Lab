-- Dual-track gold blinds: harness (judge κ) vs live production stack (capability baseline).
-- Additive only.

ALTER TABLE six_quotient_human_gold
  ADD COLUMN IF NOT EXISTS nate_response_live TEXT,
  ADD COLUMN IF NOT EXISTS live_response_provenance TEXT,
  ADD COLUMN IF NOT EXISTS live_generated_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS live_stack_run_id TEXT,
  ADD COLUMN IF NOT EXISTS live_paraphrase_used TEXT;

COMMENT ON COLUMN six_quotient_human_gold.response_provenance IS
  'unset | harness_thin_inference | live_stack_attempt | nate_genuine_attempt (legacy mislabel) | degraded_distractor_seeded | battery_transcript | clinician_authored_foil';

COMMENT ON COLUMN six_quotient_human_gold.nate_response_live IS
  'Blind generated via production therapeutic_controller + inference + verifier (capability track)';
COMMENT ON COLUMN six_quotient_human_gold.live_response_provenance IS
  'Should be live_stack_attempt when nate_response_live is set';
COMMENT ON COLUMN six_quotient_human_gold.live_stack_run_id IS
  'Batch id for within-track before/after comparisons';
COMMENT ON COLUMN six_quotient_human_gold.live_paraphrase_used IS
  'Paraphrased stem text sent to live stack (gold client_says stays quarantined)';

-- Relabel thin-harness fills that were mislabeled as genuine Nate
UPDATE six_quotient_human_gold
SET response_provenance = 'harness_thin_inference'
WHERE response_provenance = 'nate_genuine_attempt'
  AND COALESCE(is_degraded_distractor, false) = false;

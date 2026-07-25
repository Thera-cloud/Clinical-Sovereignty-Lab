-- Capability-track mode-failure tag (distinct from low clinical scores).
-- Additive only. Does not alter judge-track columns.

ALTER TABLE six_quotient_human_gold
  ADD COLUMN IF NOT EXISTS live_mode_failure TEXT;

COMMENT ON COLUMN six_quotient_human_gold.live_mode_failure IS
  'Non-response class for capability track: perspective_inversion | third_person_rp | dry_run_placeholder | null (scored clinical reply).';

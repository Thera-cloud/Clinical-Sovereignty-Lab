-- Migration 318: live_scored_via provenance flag on six_quotient_human_gold
--
-- Additive only (new nullable column). No ALTER/DROP of existing columns.
--
-- Why (TRUST_LEDGER.md Entry 10): the dose-response seed step copied 4
-- live-stack generations (AQ-1, AQ-2, AQ-G07, AQ-G08;
-- live_stack_run_id = fuel_burning_verify_20260801_affinity) out of
-- six_quotient_human_gold into quartet_dose_response_queue for the
-- 8-row move-level dose-response sitting, without writing back
-- live_human_scored = true on the source rows. Those 4 rows were then
-- re-served by the Principal-Review "Capability -- live-stack blinds"
-- track as if unscored, even though the identical response text had
-- already been human-scored at move-level in the dose-response queue.
--
-- This column lets a write-back (backend/scripts/writeback_dose_response_
-- to_live_gold.py) mark those 4 rows scored without conflating them with
-- rows scored fresh through the capability-track UI, and lets any held-out
-- kappa query (backend/scripts/compute_tier1_v5_fresh_holdout_kappa.py)
-- exclude ported rows by construction rather than by a hand-maintained
-- scenario_id blocklist.
--
-- NULL semantics: NULL = scored live through the Principal-Review
-- capability-track UI (the normal path). Non-null (e.g.
-- 'dose_response_queue') = ported from another scoring instrument;
-- MUST be excluded from any judge held-out evaluation that trained on
-- or was diagnosed against the source instrument.

ALTER TABLE six_quotient_human_gold
  ADD COLUMN IF NOT EXISTS live_scored_via TEXT;

COMMENT ON COLUMN six_quotient_human_gold.live_scored_via IS
  'NULL = scored live through the Principal-Review capability-track UI. '
  'Non-null (e.g. dose_response_queue) = ported from another scoring '
  'instrument; MUST be excluded from any judge held-out evaluation that '
  'trained or was diagnosed against the source instrument. '
  'See TRUST_LEDGER.md Entry 10.';

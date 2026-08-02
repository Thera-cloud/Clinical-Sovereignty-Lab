-- Migration 320: live_is_fallback_template flag on six_quotient_human_gold
--
-- Additive only (new nullable-default column).
--
-- Why (capability session finding, 2026-08-02): three live-track capability
-- rows (EQ-3, SQ-G07, SQ-G08) were served with the transparent audit
-- fallback string (therapeutic_controller.TRANSPARENT_AUDIT_FALLBACK_MESSAGE
-- / stall_suppression._STALL_EXACT) instead of a generated response -- the
-- audit gate's missing_somatic_invitation check fired and repeated
-- regeneration attempts still failed it. Judge and human scored the SAME
-- served text in both cases, so kappa itself is not contaminated -- but any
-- capability statistic (mean primary score, per-stem-type transfer rate,
-- "surface defects repaired" tallies) that does not separate these three
-- from genuinely-generated responses conflates the generation system's
-- output with its own error handler's output. A commitment-demand stem
-- that trips the fallback is not evidence the generator failed the
-- clinical move -- it is evidence the audit's somatic-invitation gate and
-- a direct-answer response format are in tension for that stem class.
--
-- Backfilled for the 3 known rows, and set going forward at write time by
-- live_stack_blinds.generate_live_stack_batch() via
-- stall_suppression.is_stall_fallback(text) -- no future capability run
-- needs a manual backfill pass to stay accurate.

ALTER TABLE six_quotient_human_gold
  ADD COLUMN IF NOT EXISTS live_is_fallback_template BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN six_quotient_human_gold.live_is_fallback_template IS
  'true = nate_response_live is the transparent audit fallback string '
  '(stall_suppression._STALL_EXACT), not a genuinely generated response. '
  'Set at write time by live_stack_blinds.generate_live_stack_batch(). '
  'Exclude or segment these rows before computing capability statistics '
  '(mean scores, transfer rates) -- see capability-session trace-pull '
  'finding, 2026-08-02.';

-- Backfill the 3 known instances (exact match against the frozen stall
-- string; safe to re-run, idempotent).
UPDATE six_quotient_human_gold
SET live_is_fallback_template = true
WHERE nate_response_live = (
  'I want to think about that more carefully — can you tell me which '
  'part of what you shared feels most important to you right now?'
);

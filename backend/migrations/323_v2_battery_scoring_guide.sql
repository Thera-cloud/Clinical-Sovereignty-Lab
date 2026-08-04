-- v2 battery: dedicated scoring-guide column, structurally separate from
-- client_says (docs/TIER1_HUMAN_GOLD_WORKSHEET.md's clinician-authored
-- stem intake, 2026-08-03 batch). Additive only.
--
-- This column holds the clinician's per-stem "expected clinical moves"
-- rubric annotation (what a correct response must do) -- the same
-- category of content as quartet_spine_moves.py's per-scenario move lists,
-- generalized to the six-quotient battery. It must NEVER be read by any
-- response-generation code path (fill_human_gold_nate_responses.py,
-- generate_live_stack_blinds.py, or their successors) -- those select
-- client_says only. See test_v2_battery_scoring_guide_isolation.py for
-- the mechanical fence enforcing this.

ALTER TABLE six_quotient_human_gold
    ADD COLUMN IF NOT EXISTS scoring_guide TEXT;

COMMENT ON COLUMN six_quotient_human_gold.scoring_guide IS
    'Clinician-authored expected-moves rubric for this stem (v2 battery). '
    'Reference material for the human rater only -- never selected by any '
    'response-generation query. See test_v2_battery_scoring_guide_isolation.py.';

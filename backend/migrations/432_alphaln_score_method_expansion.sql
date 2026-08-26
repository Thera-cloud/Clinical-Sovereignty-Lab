-- Migration 432: AlphaLN Phase B — expand score_method allowlist
--
-- Migration 422 stored score_method as unconstrained TEXT (default heuristic_v1).
-- This adds an explicit CHECK covering heuristic + validated-instrument methods.
-- Drop-and-recreate is safe: existing rows are heuristic_v1.

ALTER TABLE alphaln_shadow_observations
    DROP CONSTRAINT IF EXISTS alphaln_shadow_observations_score_method_check;

ALTER TABLE alphaln_shadow_observations
    ADD CONSTRAINT alphaln_shadow_observations_score_method_check
    CHECK (score_method IN (
        'heuristic_v1',
        'wai_sr_v1',
        'srs_v1',
        'phq9_delta_v1'
    ));

COMMENT ON COLUMN alphaln_shadow_observations.score_method IS
    'Scoring instrument: heuristic_v1 (default) or validated wai_sr_v1 / srs_v1 / phq9_delta_v1.';

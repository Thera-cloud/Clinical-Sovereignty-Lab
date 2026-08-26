-- Migration 431: AlphaLN Phase B — turn-to-regulation columns on gym runs
-- Additive only (ADD COLUMN IF NOT EXISTS).

ALTER TABLE alphaln_gym_runs
    ADD COLUMN IF NOT EXISTS turns_to_regulation INT,
    ADD COLUMN IF NOT EXISTS regulation_achieved BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS escalation_events INT NOT NULL DEFAULT 0;

COMMENT ON COLUMN alphaln_gym_runs.turns_to_regulation IS
    'First turn index (1-based, end of 3-turn window) where C_emo > 0.6 sustained.';
COMMENT ON COLUMN alphaln_gym_runs.regulation_achieved IS
    'True when C_emo > 0.6 for 3 consecutive scored turns.';
COMMENT ON COLUMN alphaln_gym_runs.escalation_events IS
    'Count of turns where C_emo dropped vs prior turn or distress spiked.';

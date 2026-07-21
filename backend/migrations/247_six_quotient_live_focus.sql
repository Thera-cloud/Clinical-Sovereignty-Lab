-- QUANTUM-CRYSTAL-ARCH — CEO-approved self-dev focus for live therapy cues
-- Additive only.

ALTER TABLE six_quotient_ability_state
  ADD COLUMN IF NOT EXISTS live_focus JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN six_quotient_ability_state.live_focus IS
  'CEO-approved six_quotient_self_dev focus {focus_quotient, focus_capability, approved_by, ...}';

-- Auditor denominator: +3 endpoints (generate, self-dev/trigger, standards/reject)
INSERT INTO trust_baseline (parameter_key, parameter_value, updated_at)
VALUES (
    'six_quotient_battery_check_count',
    '{"expected": 15, "description": "Six-Quotient Battery auditor endpoints (incl. gen/self-dev/reject)"}'::jsonb,
    NOW()
)
ON CONFLICT (parameter_key) DO UPDATE
SET parameter_value = jsonb_set(
        COALESCE(trust_baseline.parameter_value, '{}'::jsonb),
        '{expected}',
        '15'
    ),
    updated_at = NOW();

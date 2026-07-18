-- Migration 249: High-risk crisis auditor baseline → 10 checks
-- QUANTUM-CRYSTAL-ARCH — additive trust_baseline update only

UPDATE trust_baseline
SET parameter_value = jsonb_set(
    COALESCE(parameter_value, '{}'::jsonb),
    '{expected}',
    '10'::jsonb
)
WHERE parameter_key = 'high_risk_crisis_check_count';

INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES (
    'high_risk_crisis_check_count',
    '{"expected": 10, "description": "High-risk occupational crisis API checks"}'::jsonb
)
ON CONFLICT (parameter_key) DO UPDATE
SET parameter_value = EXCLUDED.parameter_value;

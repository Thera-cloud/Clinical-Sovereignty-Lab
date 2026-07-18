-- QUANTUM-CRYSTAL-ARCH: High-risk crisis auditor expanded to 12 checks
-- (client PUT /population + family_concern_flags DB)

UPDATE trust_baseline
SET parameter_value = jsonb_set(
        COALESCE(parameter_value, '{}'::jsonb),
        '{expected}',
        '12'
    ),
    updated_at = NOW()
WHERE parameter_key = 'high_risk_crisis_check_count';

INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES (
    'high_risk_crisis_check_count',
    '{"expected": 12, "description": "High-risk occupational crisis API + DB checks"}'::jsonb
)
ON CONFLICT (parameter_key) DO UPDATE
SET parameter_value = EXCLUDED.parameter_value,
    updated_at = NOW();

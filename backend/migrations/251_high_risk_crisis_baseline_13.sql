-- High-risk crisis auditor: 13 checks (added GET /family/members)
-- QUANTUM-CRYSTAL-ARCH

UPDATE trust_baseline
SET parameter_value = jsonb_set(
    COALESCE(parameter_value, '{}'::jsonb),
    '{expected}',
    '13'
)
WHERE parameter_key = 'high_risk_crisis_check_count';

INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES (
    'high_risk_crisis_check_count',
    '{"expected": 13, "description": "High-risk occupational crisis API checks"}'::jsonb
)
ON CONFLICT (parameter_key) DO NOTHING;

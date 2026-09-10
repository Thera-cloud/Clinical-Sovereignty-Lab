-- Attunement auditor — 8 checks (trust baseline)
-- QUANTUM-CRYSTAL-ARCH

INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES (
    'attunement_check_count',
    '{"expected": 8, "description": "Attunement hold/steer scorecard (8 DB/module checks)", "updated": "2026-09-10"}'::jsonb
)
ON CONFLICT (parameter_key) DO UPDATE
SET parameter_value = EXCLUDED.parameter_value,
    updated_at = NOW();

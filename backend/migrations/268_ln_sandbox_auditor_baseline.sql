-- LN Sandbox DOJO auditor — 8 checks (trust baseline)
-- QUANTUM-CRYSTAL-ARCH

INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES (
    'ln_sandbox_check_count',
    '{"expected": 8, "description": "LN Sandbox DOJO trust checks (5 REST + 3 DB)", "updated": "2026-07-23"}'::jsonb
)
ON CONFLICT (parameter_key) DO UPDATE
SET parameter_value = EXCLUDED.parameter_value,
    updated_at = NOW();

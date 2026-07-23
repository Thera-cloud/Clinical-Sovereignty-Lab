-- Migration 273: LN-Observer auditor baseline 11 → 13 (gap-closure admin ops)
-- QUANTUM-CRYSTAL-ARCH

INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES (
    'ln_observer_check_count',
    '{"expected": 13, "description": "LN-Observer trust checks (9 REST + 4 DB)", "updated": "2026-07-23"}'::jsonb
)
ON CONFLICT (parameter_key) DO UPDATE
SET parameter_value = EXCLUDED.parameter_value,
    updated_at = NOW();

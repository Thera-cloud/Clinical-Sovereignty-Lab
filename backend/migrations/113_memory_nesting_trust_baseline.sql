-- Migration 113: Trust baseline for Memory Nesting Auditor (1 check)
-- Integrates Memory Nesting into Trust Enforcer aggregate

INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES ('memory_nesting_check_count', '{"expected": 1}'::jsonb)
ON CONFLICT (parameter_key) DO UPDATE SET parameter_value = EXCLUDED.parameter_value, updated_at = NOW();

-- Token Lab Auditor trust baseline
-- 14 checks: 10 REST endpoints + 3 DB integrity checks + 1 health
-- Migration 073

INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES ('token_lab_check_count', '{"expected": 14, "description": "Token Lab: 10 REST endpoints + 3 DB integrity checks + 1 health", "auditor": "token_lab_auditor"}'::jsonb)
ON CONFLICT (parameter_key) DO UPDATE
SET parameter_value = EXCLUDED.parameter_value;

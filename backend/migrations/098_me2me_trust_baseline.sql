-- Migration 098: Me2Me trust baseline + DOJO Session count update
-- Adds trust_baseline row for Me2Me Pipeline Auditor (12 checks)
-- Updates DOJO Session Auditor from 29 → 30 (added consultation-status check)

INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES ('me2me_check_count', '{"expected": 12, "description": "Me2Me Legacy Pipeline — 9 REST + 3 DB checks"}'::jsonb)
ON CONFLICT (parameter_key) DO UPDATE SET parameter_value = EXCLUDED.parameter_value;

UPDATE trust_baseline
SET parameter_value = jsonb_set(parameter_value, '{expected}', '30')
WHERE parameter_key = 'dojo_session_endpoint_count';

-- Migration 134: SkyEye Tab Auditor baseline update for Monetization Control tab
-- Adds 5 endpoint checks to SkyEye auditor (58 -> 63 expected).
-- Uses INSERT ... ON CONFLICT to handle both fresh installs and existing rows.

INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES ('skyeye_endpoint_count', '{"expected": 63}'::jsonb)
ON CONFLICT (parameter_key) DO UPDATE
SET parameter_value = jsonb_set(
    COALESCE(trust_baseline.parameter_value, '{}'::jsonb),
    '{expected}',
    '63'::jsonb,
    true
);

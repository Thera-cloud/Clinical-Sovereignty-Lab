-- Migration 262: Align SkyEye trust baseline with auditor TAB_ENDPOINTS (62 endpoints / 22 tabs)
-- Auditor count verified 2026-07-21 via skyeye_tab_auditor.py TAB_ENDPOINTS sum.

UPDATE trust_baseline
SET parameter_value = jsonb_set(
    COALESCE(parameter_value, '{}'::jsonb),
    '{expected}',
    '62'::jsonb
)
WHERE parameter_key = 'skyeye_endpoint_count';

INSERT INTO trust_baseline (parameter_key, parameter_value, description, approved_by)
SELECT
    'skyeye_endpoint_count',
    '{"expected":62,"auditor":"SkyEyeTabAuditor","activity_type":"skyeye_tab_audit_sent"}'::jsonb,
    'Expected endpoint count for SkyEye dashboard auditor (62 endpoints / 22 tabs)',
    'DrNevedal1'
WHERE NOT EXISTS (
    SELECT 1 FROM trust_baseline WHERE parameter_key = 'skyeye_endpoint_count'
);

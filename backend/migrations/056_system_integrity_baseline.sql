-- 056: Seed baseline parameters for System Integrity auditor (15th auditor)
-- Expected: 18 checks (7 security posture, 4 billing shield, 7 integration sync)

INSERT INTO trust_baseline (parameter_key, parameter_value, description, approved_by) VALUES
('system_integrity_check_count',
 '{"expected":18,"auditor":"SystemIntegrityAuditor","activity_type":"system_integrity_audit_sent"}',
 'Expected check count for System Integrity auditor (security posture, billing shield, integration sync)',
 'DrNevedal1')
ON CONFLICT (parameter_key) DO NOTHING;

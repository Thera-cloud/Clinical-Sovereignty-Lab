-- 055: Seed baseline parameters for Hardware Security auditor (13th auditor)
-- Expected: 8 checks (5 profile, 1 sentinel, 2 API endpoints)

INSERT INTO trust_baseline (parameter_key, parameter_value, description, approved_by) VALUES
('hardware_security_check_count',
 '{"expected":8,"auditor":"HardwareSecurityAuditor","activity_type":"hardware_security_audit_sent"}',
 'Expected check count for Hardware Security auditor (YubiKeys, TOTP, SMS, Sentinel, APIs)',
 'DrNevedal1')
ON CONFLICT (parameter_key) DO NOTHING;

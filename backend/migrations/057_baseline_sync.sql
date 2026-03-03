-- Sync trust_baseline with actual auditor endpoint counts
-- Coach Dojo: 28 → 24 (4 endpoints were removed/consolidated)
-- Add missing baselines: HW Security (8), System Integrity (18)
-- Nevedal Lab already exists at 20 → update to 21 (added endpoint)

UPDATE trust_baseline
SET parameter_value = '{"expected":24,"auditor":"CoachDojoAuditor","activity_type":"coach_dojo_audit_sent"}'::jsonb,
    updated_at = NOW()
WHERE parameter_key = 'coach_dojo_endpoint_count';

UPDATE trust_baseline
SET parameter_value = '{"expected":21,"auditor":"NevedalLabAuditor","activity_type":"nevedal_lab_audit_sent"}'::jsonb,
    updated_at = NOW()
WHERE parameter_key = 'nevedal_lab_endpoint_count';

INSERT INTO trust_baseline (parameter_key, parameter_value, description, approved_by) VALUES
('hardware_security_check_count',
 '{"expected":8,"auditor":"HardwareSecurityAuditor","activity_type":"hardware_security_audit_sent"}',
 'Expected check count for Hardware Security auditor (WebAuthn, YubiKeys, TOTP, SMS, Sentinel, APIs)',
 'DrNevedal1'),
('system_integrity_check_count',
 '{"expected":18,"auditor":"SystemIntegrityAuditor","activity_type":"system_integrity_audit_sent"}',
 'Expected check count for System Integrity auditor (cross-system health)',
 'DrNevedal1')
ON CONFLICT (parameter_key) DO UPDATE
SET parameter_value = EXCLUDED.parameter_value,
    description = EXCLUDED.description,
    updated_at = NOW();

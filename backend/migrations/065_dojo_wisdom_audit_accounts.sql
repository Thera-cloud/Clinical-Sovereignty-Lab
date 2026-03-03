-- Migration 065: Create audit test accounts for DOJO Session Auditor
-- & Wisdom Pipeline Auditor.
-- audit_lawyer_1/2: COACH accounts for Judge DOJO multi-party testing
-- audit_student_1/2: CLIENT accounts for group session testing

INSERT INTO users (username, name, email, role, tier, hardware_id, password_hash, subscription_status, profile_data, created_at, updated_at)
VALUES
  ('audit_lawyer_1', 'Audit Lawyer 1', 'audit_lawyer_1@sovereignsanctuary.net', 'COACH', 'STANDARD', 'audit_lawyer_1_hw',
   '6ae5fbd01c70b642e4f669291576cc85:f182abe76682584000680ccb5bffb9a3ef84354a7a5d0797b2039a9468e88950',
   'ACTIVE', '{"is_audit_account": true, "created_by": "system", "dojo_type": "judge"}', NOW(), NOW()),
  ('audit_lawyer_2', 'Audit Lawyer 2', 'audit_lawyer_2@sovereignsanctuary.net', 'COACH', 'STANDARD', 'audit_lawyer_2_hw',
   'a9b4012069c59e752e14fd67bad46818:6adc4b0230045e46519e81050a2a5714a62860eaaf450eefd5207e86bd23c705',
   'ACTIVE', '{"is_audit_account": true, "created_by": "system", "dojo_type": "judge"}', NOW(), NOW()),
  ('audit_student_1', 'Audit Student 1', 'audit_student_1@sovereignsanctuary.net', 'CLIENT', 'STANDARD', 'audit_student_1_hw',
   '6ae5fbd01c70b642e4f669291576cc85:f182abe76682584000680ccb5bffb9a3ef84354a7a5d0797b2039a9468e88950',
   'ACTIVE', '{"tier": "inner_chamber", "is_audit_account": true, "created_by": "system"}', NOW(), NOW()),
  ('audit_student_2', 'Audit Student 2', 'audit_student_2@sovereignsanctuary.net', 'CLIENT', 'STANDARD', 'audit_student_2_hw',
   'a9b4012069c59e752e14fd67bad46818:6adc4b0230045e46519e81050a2a5714a62860eaaf450eefd5207e86bd23c705',
   'ACTIVE', '{"tier": "inner_chamber", "is_audit_account": true, "created_by": "system"}', NOW(), NOW())
ON CONFLICT (username) DO NOTHING;

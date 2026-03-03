-- Migration 054: Create audit test accounts for LoginAuditor & WebSocketFlowAuditor
-- These are non-interactive service accounts used by automated trust auditors.

INSERT INTO users (hardware_id, name, email, role, subscription_status, password_hash, profile_data, created_at)
VALUES
  ('audit_client_hw', 'audit_client', 'audit_client@sovereignsanctuary.net', 'CLIENT', 'active',
   '6ae5fbd01c70b642e4f669291576cc85:f182abe76682584000680ccb5bffb9a3ef84354a7a5d0797b2039a9468e88950',
   '{"tier": "sovereign_circle", "is_audit_account": true, "created_by": "system"}',
   NOW()),
  ('audit_coach_hw', 'audit_coach', 'audit_coach@sovereignsanctuary.net', 'COACH', 'active',
   'a9b4012069c59e752e14fd67bad46818:6adc4b0230045e46519e81050a2a5714a62860eaaf450eefd5207e86bd23c705',
   '{"is_audit_account": true, "created_by": "system"}',
   NOW())
ON CONFLICT (hardware_id) DO NOTHING;

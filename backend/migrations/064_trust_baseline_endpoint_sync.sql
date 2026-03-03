-- Migration 064: Sync trust_baseline with new auditor endpoint counts
-- Billing: 20 → 23 (added IAP receipt validation: apple, google, restore)
-- Client App: 15 → 23 (added community mesh, data export, call history)

UPDATE trust_baseline
SET parameter_value = '{"expected":23,"auditor":"BillingPipelineAuditor","activity_type":"billing_audit_sent"}'::jsonb,
    updated_at = NOW()
WHERE parameter_key = 'billing_endpoint_count';

UPDATE trust_baseline
SET parameter_value = '{"expected":23,"auditor":"ClientAppAuditor","activity_type":"client_app_audit_sent"}'::jsonb,
    updated_at = NOW()
WHERE parameter_key = 'client_app_endpoint_count';

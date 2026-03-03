-- Migration 067: Trust baseline for Settings Tab Auditor (15 checks across 8 tabs)
-- 10 REST endpoints + 5 WebSocket checks = 15

INSERT INTO trust_baseline (parameter_key, parameter_value, updated_at)
VALUES
  ('settings_tab_check_count',
   '{"expected":15,"auditor":"SettingsTabAuditor","activity_type":"settings_tab_audit_sent"}'::jsonb,
   NOW())
ON CONFLICT (parameter_key) DO UPDATE
SET parameter_value = EXCLUDED.parameter_value,
    updated_at = NOW();

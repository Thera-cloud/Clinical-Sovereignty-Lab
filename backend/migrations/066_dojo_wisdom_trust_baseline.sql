-- Migration 066: Trust baseline entries for DOJO Session Auditor (29 endpoints)
-- and Wisdom Pipeline Auditor (12 checks). Coach & DOJO Auditor updated to 46.

INSERT INTO trust_baseline (parameter_key, parameter_value, updated_at)
VALUES
  ('dojo_session_endpoint_count',
   '{"expected":29,"auditor":"DojoSessionAuditor","activity_type":"dojo_session_audit_sent"}'::jsonb,
   NOW()),
  ('wisdom_pipeline_check_count',
   '{"expected":12,"auditor":"WisdomPipelineAuditor","activity_type":"wisdom_pipeline_audit_sent"}'::jsonb,
   NOW())
ON CONFLICT (parameter_key) DO UPDATE
SET parameter_value = EXCLUDED.parameter_value,
    updated_at = NOW();

UPDATE trust_baseline
SET parameter_value = '{"expected":46,"auditor":"CoachDojoAuditor","activity_type":"coach_dojo_audit_sent"}'::jsonb,
    updated_at = NOW()
WHERE parameter_key = 'coach_dojo_endpoint_count';

-- Migration 202: Sensitive Clinical Bridge Core
-- Plan: docs/plan_backups/sensitive_clinical_bridge_v1.3.backup.2026-05-08-1402.plan.md (Gap C, Gap E)
-- Domain: physical intimacy work + trafficking-survivor bridge support
-- Compliance: Illinois MHDDCA 740 ILCS 110 + HIPAA 45 CFR 164.530(j) (7-year retention)
--
-- This migration is the FOUNDATION for all subsequent sensitive-bridge migrations (203-208).
-- It must apply BEFORE migrations 203-208.
--
-- Notes:
-- 1. The 5 new crystal domains (intimacy_clinical, purity_culture, infidelity_recovery,
--    sexual_trauma, trafficking_trauma) are reserved as canonical VARCHAR values used by
--    bulk_crystal_ingestion.py. We deliberately do NOT add a CHECK constraint on
--    nate_intelligence_crystals.domain because:
--      (a) The existing column has no constraint and may contain free-form values
--          accumulated over time. Adding a CHECK retroactively would risk failing on
--          legacy rows.
--      (b) Domain canonicalization is enforced at the application layer in
--          bulk_crystal_ingestion.py per the plan.
--    DRIFT GUARD: Phase 6 reserves auditor check `crystal_domain_canonical_set`
--    (sensitive_bridge_auditor.py) which scans DISTINCT domain values monthly and
--    alerts if a non-canonical domain is found. This protects against ingestion
--    paths that bypass bulk_crystal_ingestion.py.
-- 2. IMMUTABLE_TYPES seeding for 'sensitive_bridge_log' is a CODE change to
--    backend/app/services/db_maintenance_agent.py — handled in a later phase, not here.
-- 3. payload_json and decision_summary MUST NOT contain raw user/AI text. The validator
--    enforces this at insert time via pii_screened_at column.
-- 4. RETENTION POLICY (Gap L jurisdiction overlay):
--    Default retained_until = NOW() + INTERVAL '7 years' is the most-protective default
--    (Illinois MHDDCA 740 ILCS 110 + HIPAA 45 CFR 164.530(j) extended to 7yr).
--    Phase 4 (Gap L) will add a BEFORE INSERT trigger that reads
--    users.profile_data->>'jurisdiction_state' and adjusts retained_until per the
--    jurisdiction policy table:
--        IL/CA/NY = 7 years   (matches default — no change)
--        FL       = 6 years
--        TX       = 5 years
--        unknown  = 7 years   (most-protective fallback / locale_fallback_applied event)
--    The orchestrator in Phase 4 onward writes correctly because the trigger fires at
--    INSERT time. Rows inserted between Phase 1 and Phase 4 will all carry 7yr,
--    which is safe (over-retention does not violate any statute we cover).
-- 5. EVENT_TYPE CATALOG: 33 canonical event types as of v1.3. Adding a new event_type
--    requires (a) ALTER TABLE ... DROP CONSTRAINT + ADD CONSTRAINT in a follow-up
--    migration, (b) update to docs/SENSITIVE_CLINICAL_BRIDGE_GUIDELINES_2026-05-08.md,
--    (c) 5-location trust-enforcer sync if the auditor counts events.

-- ============================================================
-- sensitive_bridge_log — append-only audit trail (Gap C)
-- ============================================================

CREATE TABLE IF NOT EXISTS sensitive_bridge_log (
  id BIGSERIAL PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(username) ON DELETE RESTRICT,
  session_id TEXT,
  event_type TEXT NOT NULL CHECK (event_type IN (
    'disclosure_evaluated',
    'introjection_detected',
    'codeword_triggered',
    'codeword_triggered_with_mandatory_reporting_path',
    'arousal_cap_triggered',
    'thalamic_gate_blocked',
    'trigger_date_active',
    'embodiment_phase_filter_applied',
    'reengagement_pattern_detected',
    'polyvictim_load_applied',
    'legal_event_proximity_detected',
    'dual_diagnosis_register_applied',
    'safe_silence_mode_state_change',
    'safe_silence_mode_expiry_warning',
    'safe_silence_mode_auto_reverted',
    'sensitive_profile_mutation',
    'validator_lexicon_filter_applied',
    'validator_minor_protection_filter',
    'validator_parenting_pathologization_filter',
    'reporting_trigger_fired',
    'coach_handoff_emitted',
    'active_trafficking_disclosed',
    'imminent_danger_detected',
    'survivor_recruiter_role_disclosed',
    'jurisdiction_policy_applied',
    'survivor_data_export_requested',
    'minor_survivor_mandatory_reporting_auto_fired',
    'guardian_dual_approval_required',
    'parenting_crisis_alert_fired',
    'rj_companioning_register_applied',
    'cultural_context_register_applied',
    'locale_fallback_applied',
    'gap_feature_auto_disabled'
  )),
  event_severity TEXT NOT NULL CHECK (event_severity IN (
    'info','low','moderate','high','critical','emergency'
  )),
  payload_json JSONB NOT NULL,
  decision_summary JSONB,
  occurred_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  recorded_by TEXT NOT NULL DEFAULT 'sensitive_clinical_bridge',
  retained_until TIMESTAMP WITH TIME ZONE NOT NULL
    DEFAULT (NOW() + INTERVAL '7 years'),
  access_classification TEXT NOT NULL CHECK (access_classification IN (
    'clinician_only',
    'clinician_and_admin',
    'admin_only_redacted'
  )) DEFAULT 'clinician_and_admin',
  pii_screened_at TIMESTAMP WITH TIME ZONE,
  redaction_pass_count INT NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_sensitive_log_user_recent
  ON sensitive_bridge_log(user_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_sensitive_log_event_type
  ON sensitive_bridge_log(event_type, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_sensitive_log_retention
  ON sensitive_bridge_log(retained_until);
CREATE INDEX IF NOT EXISTS idx_sensitive_log_severity
  ON sensitive_bridge_log(event_severity, occurred_at DESC)
  WHERE event_severity IN ('critical','emergency');

-- Documentation comment so DBAs understand the retention/access model
COMMENT ON TABLE sensitive_bridge_log IS
  'Audit trail for sensitive clinical bridge events. 7-year retention per Illinois MHDDCA + HIPAA. '
  'IMMUTABLE: never auto-pruned by db_maintenance_agent. Manual purge requires admin + WebAuthn YubiKey. '
  'payload_json and decision_summary MUST NOT contain raw user or AI text. PII pre-insert screen enforced by validator.';

COMMENT ON COLUMN sensitive_bridge_log.access_classification IS
  'RBAC classification: clinician_only = treating clinician only; clinician_and_admin = both; '
  'admin_only_redacted = admin-redacted view only (clinician notes stripped).';

COMMENT ON COLUMN sensitive_bridge_log.pii_screened_at IS
  'Set by nate_response_validator after PII pattern screen passes. NULL means screen has not run.';

COMMENT ON COLUMN sensitive_bridge_log.retained_until IS
  'Most-protective default = NOW() + 7 years (matches IL/CA/NY + HIPAA-extended). '
  'Phase 4 Gap L adds a BEFORE INSERT trigger that overrides per '
  'users.profile_data->>jurisdiction_state. Do NOT shorten retention via UPDATE — '
  'only INSERT-time computation is permitted. Manual extension is allowed only by '
  'admin + WebAuthn YubiKey.';

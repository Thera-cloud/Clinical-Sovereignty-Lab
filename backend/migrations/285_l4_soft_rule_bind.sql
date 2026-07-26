-- QUANTUM-CRYSTAL-ARCH: L4a soft-gate rule bind — audit actions + seed sandbox rule
-- Soft classes only. No SI/violence rules.

ALTER TABLE ln_rule_audit DROP CONSTRAINT IF EXISTS ln_rule_audit_action_check;
ALTER TABLE ln_rule_audit ADD CONSTRAINT ln_rule_audit_action_check
    CHECK (action IN (
        'draft', 'sandbox_pass', 'sandbox_fail', 'promote', 'rollback',
        'fire', 'shadow_fire'
    ));

-- One soft follow-up suppress rule (sandbox). Auto-promotes when
-- clinical_gate_confidence sample_size/confidence thresholds are met.
INSERT INTO ln_rule_store (
    rule_key, version, status, condition_json, action_json, created_by, notes
)
VALUES (
    'soft_gate.diagnosis_request.followup_suppress',
    1,
    'sandbox',
    '{"gate_class":"diagnosis_request","fired_new":false,"max_confidence":0.30}'::jsonb,
    '{"type":"suppress_soft_followup"}'::jsonb,
    'system',
    'L4a seed — suppress soft diagnosis follow-ups when gate confidence is low'
)
ON CONFLICT (rule_key, version) DO NOTHING;

INSERT INTO ln_rule_audit (rule_key, version, action, detail)
SELECT
    'soft_gate.diagnosis_request.followup_suppress',
    1,
    'draft',
    'seeded sandbox via migration 285'
WHERE NOT EXISTS (
    SELECT 1 FROM ln_rule_audit
    WHERE rule_key = 'soft_gate.diagnosis_request.followup_suppress'
      AND version = 1
      AND action = 'draft'
);

INSERT INTO ln_rule_audit (rule_key, version, action, detail)
SELECT
    'soft_gate.diagnosis_request.followup_suppress',
    1,
    'sandbox_pass',
    'seed status=sandbox'
WHERE NOT EXISTS (
    SELECT 1 FROM ln_rule_audit
    WHERE rule_key = 'soft_gate.diagnosis_request.followup_suppress'
      AND version = 1
      AND action = 'sandbox_pass'
);

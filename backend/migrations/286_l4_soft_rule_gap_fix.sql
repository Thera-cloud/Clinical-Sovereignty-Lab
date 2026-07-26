-- QUANTUM-CRYSTAL-ARCH: L4a gap fix — activate soft follow-up rules for all soft classes
-- Never seeds SI/violence. Soft runtime-gate classes only.

-- Diagnosis: promote seed to active; drop max_confidence so follow-ups bind when fired_new=false
UPDATE ln_rule_store
SET status = 'active',
    promoted_at = COALESCE(promoted_at, NOW()),
    condition_json = '{"gate_class":"diagnosis_request","fired_new":false}'::jsonb,
    notes = 'L4a active — suppress soft diagnosis follow-ups'
WHERE rule_key = 'soft_gate.diagnosis_request.followup_suppress'
  AND version = 1
  AND status IN ('sandbox', 'draft', 'active');

INSERT INTO ln_rule_audit (rule_key, version, action, detail)
SELECT
    'soft_gate.diagnosis_request.followup_suppress',
    1,
    'promote',
    'migration 286 activate seed'
WHERE NOT EXISTS (
    SELECT 1 FROM ln_rule_audit
    WHERE rule_key = 'soft_gate.diagnosis_request.followup_suppress'
      AND version = 1
      AND action = 'promote'
      AND detail = 'migration 286 activate seed'
);

-- Remaining soft classes — active follow-up suppress (same action allowlist)
INSERT INTO ln_rule_store (
    rule_key, version, status, condition_json, action_json, created_by, notes, promoted_at
)
VALUES
(
    'soft_gate.pharma_interaction.followup_suppress',
    1, 'active',
    '{"gate_class":"pharma_interaction","fired_new":false}'::jsonb,
    '{"type":"suppress_soft_followup"}'::jsonb,
    'system', 'L4a soft pharma follow-up suppress', NOW()
),
(
    'soft_gate.sleep_aid.followup_suppress',
    1, 'active',
    '{"gate_class":"sleep_aid","fired_new":false}'::jsonb,
    '{"type":"suppress_soft_followup"}'::jsonb,
    'system', 'L4a soft sleep follow-up suppress', NOW()
),
(
    'soft_gate.clinical_instrument.followup_suppress',
    1, 'active',
    '{"gate_class":"clinical_instrument","fired_new":false}'::jsonb,
    '{"type":"suppress_soft_followup"}'::jsonb,
    'system', 'L4a soft instrument follow-up suppress', NOW()
),
(
    'soft_gate.credential_bypass.followup_suppress',
    1, 'active',
    '{"gate_class":"credential_bypass","fired_new":false}'::jsonb,
    '{"type":"suppress_soft_followup"}'::jsonb,
    'system', 'L4a soft credential follow-up suppress', NOW()
)
ON CONFLICT (rule_key, version) DO UPDATE SET
    status = 'active',
    condition_json = EXCLUDED.condition_json,
    action_json = EXCLUDED.action_json,
    promoted_at = COALESCE(ln_rule_store.promoted_at, NOW()),
    notes = EXCLUDED.notes;

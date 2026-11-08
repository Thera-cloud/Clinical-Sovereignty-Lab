-- Additive: Billing auditor Session Ops Integrity tab (3 DB checks) → 38 expected.
UPDATE trust_baseline
   SET parameter_value = jsonb_set(parameter_value, '{expected}', '38')
 WHERE parameter_key = 'billing_endpoint_count';

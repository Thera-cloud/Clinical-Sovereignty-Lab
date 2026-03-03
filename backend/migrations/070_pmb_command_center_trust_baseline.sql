-- PMB Command Center Trust Baseline
-- Adds the expected endpoint count for the PMB Command Center Auditor
-- 13 endpoints across 4 tabs: Globe (4), Client Detail (1), Report Governance (4), Report Actions (4)

INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES ('pmb_command_center_check_count', '{"expected": 13, "description": "PMB Command Center: Globe Command Center (4) + Client Detail (1) + Report Governance (4) + Report Actions (4)"}')
ON CONFLICT (parameter_key) DO UPDATE SET parameter_value = EXCLUDED.parameter_value;

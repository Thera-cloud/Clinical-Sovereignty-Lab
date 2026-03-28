-- Migration 125: Phase 6 — Trust baselines for 4 new auditors
-- Summon System (8 checks), Crystallization Pipeline (10 checks),
-- Inference Pipeline (8 checks), Distributed Defense Shield (8 checks)

INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES
    ('summon_check_count', '{"expected": 8, "description": "Summon System auditor: 5 REST + 3 REST"}'),
    ('crystallization_check_count', '{"expected": 10, "description": "Crystal Pipeline auditor: 6 REST + 4 DB"}'),
    ('inference_check_count', '{"expected": 8, "description": "Inference Pipeline auditor: 5 REST + 3 DB"}'),
    ('defense_shield_check_count', '{"expected": 8, "description": "Distributed Defense Shield auditor: 5 REST + 3 DB"}')
ON CONFLICT (parameter_key) DO UPDATE
SET parameter_value = EXCLUDED.parameter_value;

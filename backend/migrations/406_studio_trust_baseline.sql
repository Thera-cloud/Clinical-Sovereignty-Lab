-- Sovereign Studio auditor baseline — 15 checks. QUANTUM-CRYSTAL-ARCH
-- 5-location sync: AUDITOR_ACTIVITY_TYPES, AUDITOR_LABELS, _baseline_key_for,
-- this row, main.py _service_checks.

INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES (
    'studio_check_count',
    '{"expected": 15, "description": "Sovereign Studio: show/persona (4) + session/wall (3) + screener/SIP (4) + episode/compliance (3) + RSS publish (1)"}'
)
ON CONFLICT (parameter_key) DO UPDATE SET parameter_value = EXCLUDED.parameter_value;

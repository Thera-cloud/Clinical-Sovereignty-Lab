-- Sovereign Studio auditor baseline — 19 checks. QUANTUM-CRYSTAL-ARCH
-- Additive: Booth/Live coach-JWT probes (delay, dump, share-asset, lookup).
-- 5-location sync: TAB_ENDPOINTS, AUDITOR_ACTIVITY_TYPES, AUDITOR_LABELS,
-- _baseline_key_for, this row.

INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES (
    'studio_check_count',
    '{"expected": 19, "description": "Sovereign Studio: show/persona (4) + session/wall (3) + screener/SIP (4) + episode/compliance (3) + RSS publish (1) + booth/live (4)"}'
)
ON CONFLICT (parameter_key) DO UPDATE SET parameter_value = EXCLUDED.parameter_value;

-- Migration 436: Client App +5 thrive wiring (healing-signal, focus, practices, practice-log, coach roster)
-- Client App: 30 -> 35   (QUANTUM-CRYSTAL-ARCH)

UPDATE trust_baseline
SET parameter_value = jsonb_set(COALESCE(parameter_value, '{}'::jsonb), '{expected}', '35'),
    updated_at = NOW()
WHERE parameter_key = 'client_app_endpoint_count';

-- Migration 435: Client App +5 for Growth Phase & Thrive tab (thrive_api health/catalog/frameworks/phase/brief)
-- Client App: 25 -> 30   (QUANTUM-CRYSTAL-ARCH — pairs with 434_growth_phase.sql)

UPDATE trust_baseline
SET parameter_value = jsonb_set(COALESCE(parameter_value, '{}'::jsonb), '{expected}', '30'),
    updated_at = NOW()
WHERE parameter_key = 'client_app_endpoint_count';

-- Migration 112: Client App +1 for GET /api/client/health-check (Client Data Sync tab)
-- Client App: 25 -> 26

UPDATE trust_baseline
SET parameter_value = jsonb_set(COALESCE(parameter_value, '{}'::jsonb), '{expected}', '26')
WHERE parameter_key = 'client_app_endpoint_count';

-- Migration 111: Trust baseline for new coach INSIGHTS history and client check-in reply endpoints
-- Coach & DOJO: +1 (GET /api/coach/insights/history) -> 56
-- Client App: +2 (GET /api/client/checkin-reply, POST .../read) -> 25

UPDATE trust_baseline
SET parameter_value = jsonb_set(COALESCE(parameter_value, '{}'::jsonb), '{expected}', '56')
WHERE parameter_key = 'coach_dojo_endpoint_count';

UPDATE trust_baseline
SET parameter_value = jsonb_set(COALESCE(parameter_value, '{}'::jsonb), '{expected}', '25')
WHERE parameter_key = 'client_app_endpoint_count';

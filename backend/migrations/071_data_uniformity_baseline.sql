-- Migration 071: Data Uniformity Baseline
-- Syncs dedicated PG columns with profile_data JSONB values,
-- aligns coach assignment triple fields, and seeds the trust baseline
-- for the 20-check Data Uniformity Tracer agent.

BEGIN;

-- =========================================================================
-- 1. Sync token_balance column from JSONB (JSONB is authoritative)
-- =========================================================================
UPDATE users SET
  token_balance = COALESCE((profile_data->>'token_balance')::int, token_balance, 0)
WHERE role IN ('CLIENT', 'COACH')
  AND profile_data->>'token_balance' IS NOT NULL
  AND (
    token_balance IS NULL
    OR token_balance != (profile_data->>'token_balance')::int
  );

-- =========================================================================
-- 2. Sync login_count column from JSONB
-- =========================================================================
UPDATE users SET
  login_count = COALESCE((profile_data->>'login_count')::int, login_count, 0)
WHERE role IN ('CLIENT', 'COACH')
  AND profile_data->>'login_count' IS NOT NULL
  AND (
    login_count IS NULL
    OR login_count != (profile_data->>'login_count')::int
  );

-- =========================================================================
-- 3. Coach assignment triple-field alignment
--    Where assigned_coach_id is set but coach_id is missing/mismatched,
--    copy assigned_coach_id into coach_id
-- =========================================================================
UPDATE users SET
  profile_data = jsonb_set(
    profile_data,
    '{coach_id}',
    COALESCE(profile_data->'assigned_coach_id', '""'::jsonb)
  )
WHERE role = 'CLIENT'
  AND profile_data->>'assigned_coach_id' IS NOT NULL
  AND profile_data->>'assigned_coach_id' != ''
  AND (
    profile_data->>'coach_id' IS NULL
    OR profile_data->>'coach_id' = ''
    OR profile_data->>'coach_id' != profile_data->>'assigned_coach_id'
  );

-- Where coach_id is set but assigned_coach_id is missing, copy the other way
UPDATE users SET
  profile_data = jsonb_set(
    profile_data,
    '{assigned_coach_id}',
    COALESCE(profile_data->'coach_id', '""'::jsonb)
  )
WHERE role = 'CLIENT'
  AND profile_data->>'coach_id' IS NOT NULL
  AND profile_data->>'coach_id' != ''
  AND (
    profile_data->>'assigned_coach_id' IS NULL
    OR profile_data->>'assigned_coach_id' = ''
  );

-- Resolve assigned_coach username from the coach's hardware_id
-- (only where assigned_coach is missing but assigned_coach_id is set)
UPDATE users AS c SET
  profile_data = jsonb_set(
    c.profile_data,
    '{assigned_coach}',
    to_jsonb(coach.username)
  )
FROM users AS coach
WHERE c.role = 'CLIENT'
  AND coach.role = 'COACH'
  AND coach.hardware_id = c.profile_data->>'assigned_coach_id'
  AND c.profile_data->>'assigned_coach_id' IS NOT NULL
  AND c.profile_data->>'assigned_coach_id' != ''
  AND (
    c.profile_data->>'assigned_coach' IS NULL
    OR c.profile_data->>'assigned_coach' = ''
  );

-- =========================================================================
-- 4. Trust baseline for Data Uniformity Tracer (20 checks)
-- =========================================================================
INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES ('data_uniformity_check_count', '{"expected": 20, "description": "Data Uniformity Tracer: 3 column/JSONB sync + 4 cross-surface + 4 billing + 3 coach assignment + 3 geo-location + 3 zero-value anomaly checks"}')
ON CONFLICT (parameter_key) DO UPDATE SET
  parameter_value = '{"expected": 20, "description": "Data Uniformity Tracer: 3 column/JSONB sync + 4 cross-surface + 4 billing + 3 coach assignment + 3 geo-location + 3 zero-value anomaly checks"}';

COMMIT;

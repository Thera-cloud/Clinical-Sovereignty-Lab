-- QUANTUM-CRYSTAL-ARCH — D.13 acceleration: world-model + PGSD + trend meta
-- Additive only.

ALTER TABLE six_quotient_theta_trend
  ADD COLUMN IF NOT EXISTS world_model_brier DOUBLE PRECISION;

ALTER TABLE six_quotient_theta_trend
  ADD COLUMN IF NOT EXISTS world_model_n INT NOT NULL DEFAULT 0;

ALTER TABLE six_quotient_theta_trend
  ADD COLUMN IF NOT EXISTS pgsd_coherence_delta DOUBLE PRECISION;

ALTER TABLE six_quotient_theta_trend
  ADD COLUMN IF NOT EXISTS pgsd_n_clients INT NOT NULL DEFAULT 0;

ALTER TABLE six_quotient_theta_trend
  ADD COLUMN IF NOT EXISTS acceleration_meta JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN six_quotient_theta_trend.world_model_brier IS
  'Aggregated Brier (≥5 clients) for resolved cycle/therapeutic predictions';
COMMENT ON COLUMN six_quotient_theta_trend.pgsd_coherence_delta IS
  'Mean PGSD coherence delta across ≥5 clients (live outcome channel)';

INSERT INTO trust_baseline (parameter_key, parameter_value, updated_at)
VALUES (
    'six_quotient_battery_check_count',
    '{"expected": 18, "description": "Six-Quotient Battery auditor (incl. acceleration)"}'::jsonb,
    NOW()
)
ON CONFLICT (parameter_key) DO UPDATE
SET parameter_value = jsonb_set(
        COALESCE(trust_baseline.parameter_value, '{}'::jsonb),
        '{expected}',
        '18'
    ),
    updated_at = NOW();

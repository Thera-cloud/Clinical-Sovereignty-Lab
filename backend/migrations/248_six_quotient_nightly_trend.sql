-- QUANTUM-CRYSTAL-ARCH — Nightly measure / weekly act (Track D.12)
-- Additive only: holdout columns, run_kind, theta trend table, auditor baseline 17.

ALTER TABLE six_quotient_scenario_bank
  ADD COLUMN IF NOT EXISTS held_out BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE six_quotient_scenario_bank
  ADD COLUMN IF NOT EXISTS last_measured_at TIMESTAMPTZ;

ALTER TABLE six_quotient_runs
  ADD COLUMN IF NOT EXISTS run_kind TEXT NOT NULL DEFAULT 'weekly';

COMMENT ON COLUMN six_quotient_scenario_bank.held_out IS
  'Transfer-set items — measured separately; never feed live ability from held-out runs';
COMMENT ON COLUMN six_quotient_runs.run_kind IS
  'weekly | nightly | transfer — measurement cadence tag';

CREATE TABLE IF NOT EXISTS six_quotient_theta_trend (
    id BIGSERIAL PRIMARY KEY,
    environment TEXT NOT NULL,
    run_id UUID,
    run_kind TEXT NOT NULL,
    theta DOUBLE PRECISION NOT NULL,
    theta_by_section JSONB NOT NULL DEFAULT '{}'::jsonb,
    seen_theta DOUBLE PRECISION,
    held_out_theta DOUBLE PRECISION,
    scenario_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sq_trend_env_time
  ON six_quotient_theta_trend (environment, created_at DESC);

INSERT INTO trust_baseline (parameter_key, parameter_value, updated_at)
VALUES (
    'six_quotient_battery_check_count',
    '{"expected": 17, "description": "Six-Quotient Battery auditor endpoints (incl. trend + holdout)"}'::jsonb,
    NOW()
)
ON CONFLICT (parameter_key) DO UPDATE
SET parameter_value = jsonb_set(
        COALESCE(trust_baseline.parameter_value, '{}'::jsonb),
        '{expected}',
        '17'
    ),
    updated_at = NOW();

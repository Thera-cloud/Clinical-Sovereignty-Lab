-- Migration 129: Predictive Intelligence Engine + Cycle Detection Engine
-- Creates 5 tables for the unified prediction and cycle detection system

-- Therapeutic habit tracking (individual habit formation journeys)
CREATE TABLE IF NOT EXISTS therapeutic_habit_tracking (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(128) NOT NULL,
    habit_type VARCHAR(100) NOT NULL,
    habit_description TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    target_days INTEGER DEFAULT 66,
    current_streak INTEGER DEFAULT 0,
    longest_streak INTEGER DEFAULT 0,
    total_completions INTEGER DEFAULT 0,
    total_misses INTEGER DEFAULT 0,
    status VARCHAR(32) DEFAULT 'active',
    predicted_adoption_days INTEGER,
    predicted_crystallization_days INTEGER,
    predicted_maintenance_probability REAL,
    prediction_metadata JSONB DEFAULT '{}',
    last_completion_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_habit_user ON therapeutic_habit_tracking(user_id, status);

-- Therapeutic predictions (master formula outputs + accuracy tracking)
CREATE TABLE IF NOT EXISTS therapeutic_predictions (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(128) NOT NULL,
    family_id VARCHAR(128),
    prediction_type VARCHAR(50) NOT NULL,
    goal_type VARCHAR(100),
    success_probability REAL NOT NULL,
    confidence_score REAL NOT NULL,
    nevedal_base_score REAL,
    components JSONB NOT NULL DEFAULT '{}',
    key_amplifiers JSONB,
    key_resistances JSONB,
    optimal_intervention_plan JSONB,
    prediction_horizon_days INTEGER,
    actual_outcome REAL,
    accuracy_score REAL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pred_user ON therapeutic_predictions(user_id, prediction_type, created_at DESC);

-- Cycle observations (raw signal values per user per domain per timestamp)
CREATE TABLE IF NOT EXISTS cycle_observations (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(128) NOT NULL,
    domain VARCHAR(32) NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    value DOUBLE PRECISION NOT NULL,
    phase VARCHAR(16),
    metadata JSONB DEFAULT '{}',
    UNIQUE(user_id, domain, observed_at)
);
CREATE INDEX IF NOT EXISTS idx_cycle_obs_user_domain ON cycle_observations(user_id, domain, observed_at DESC);

-- Cycle detections (detected periodicities from FFT/autocorrelation)
CREATE TABLE IF NOT EXISTS cycle_detections (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(128) NOT NULL,
    domain VARCHAR(32) NOT NULL,
    detected_period_days DOUBLE PRECISION NOT NULL,
    amplitude DOUBLE PRECISION NOT NULL,
    phase_offset DOUBLE PRECISION DEFAULT 0,
    confidence DOUBLE PRECISION NOT NULL,
    method VARCHAR(32) DEFAULT 'fft',
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_cycle_det_user ON cycle_detections(user_id, domain);

-- Cycle predictions (forecasted cycle events + intervention windows)
CREATE TABLE IF NOT EXISTS cycle_predictions (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(128) NOT NULL,
    domain VARCHAR(32) NOT NULL,
    predicted_event VARCHAR(32) NOT NULL,
    predicted_at TIMESTAMPTZ NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    intervention_window_start TIMESTAMPTZ,
    intervention_window_end TIMESTAMPTZ,
    convergence_risk DOUBLE PRECISION DEFAULT 0,
    converging_domains JSONB DEFAULT '[]',
    status VARCHAR(16) DEFAULT 'pending',
    actual_outcome VARCHAR(32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cycle_pred_user ON cycle_predictions(user_id, domain, predicted_at);

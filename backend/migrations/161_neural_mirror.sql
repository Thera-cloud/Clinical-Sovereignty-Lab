-- Migration 161: Neural Mirror System tables
-- Patent 11: Virtual EEG Fingerprinting, Emotional DNA, Neural Mirror Co-regulation

-- Voice emotional baselines (Phase 2)
CREATE TABLE IF NOT EXISTS voice_emotional_baselines (
    baseline_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    emotion TEXT NOT NULL,
    audio_data BYTEA,
    feature_vector JSONB,
    latent_vector JSONB,
    session_id UUID,
    nevedal_ec_score FLOAT,
    confidence FLOAT DEFAULT 0.0,
    context_summary TEXT,
    captured_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_veb_user_emotion ON voice_emotional_baselines (user_id, emotion);

-- Neural fingerprints (Phase 4)
CREATE TABLE IF NOT EXISTS neural_fingerprints (
    fingerprint_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL UNIQUE,
    mean_vector JSONB,
    covariance JSONB,
    gmm_params JSONB,
    n_samples INT DEFAULT 0,
    emotional_baselines JSONB,
    calibrated BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_nfp_user ON neural_fingerprints (user_id);

-- Virtual EEG traces (Phase 8)
CREATE TABLE IF NOT EXISTS virtual_eeg_traces (
    trace_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    session_id UUID,
    latent_vectors JSONB,
    band_energies JSONB,
    nevedal_factors JSONB,
    dominant_bands JSONB,
    mirror_states JSONB,
    tunneling_events JSONB,
    duration_seconds FLOAT DEFAULT 0.0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vet_user ON virtual_eeg_traces (user_id);
CREATE INDEX IF NOT EXISTS idx_vet_session ON virtual_eeg_traces (session_id);
CREATE INDEX IF NOT EXISTS idx_vet_created ON virtual_eeg_traces (created_at DESC);

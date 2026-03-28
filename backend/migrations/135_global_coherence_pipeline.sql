-- Migration 135: Global Coherence Aggregation Pipeline
-- Adds ODPE signal logging and global coherence snapshot persistence

-- ODPE signal log — one row per helix orchestrator think() cycle
CREATE TABLE IF NOT EXISTS odpe_signal_log (
    id BIGSERIAL PRIMARY KEY,
    cycle_id UUID NOT NULL,
    dominant_signal VARCHAR(16) NOT NULL,
    dodec_amplitude DECIMAL(6,5),
    icosi_amplitude DECIMAL(6,5),
    resonance_ratio DECIMAL(8,5),
    context_tokens_recommended INTEGER,
    inference_tier VARCHAR(16),
    per_helix_signals JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_odpe_signal_created ON odpe_signal_log(created_at);

-- Global coherence snapshots — persisted every 5 min by GlobalCoherenceAggregator
CREATE TABLE IF NOT EXISTS global_coherence_snapshots (
    id BIGSERIAL PRIMARY KEY,
    snapshot_id UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    global_c_emo DECIMAL(6,5) NOT NULL,
    active_sessions INTEGER DEFAULT 0,
    active_users INTEGER DEFAULT 0,
    cee_density DECIMAL(6,5) DEFAULT 0,
    odpe_distribution JSONB DEFAULT '{}',
    layer_scores JSONB DEFAULT '{}',
    cycle_signals JSONB DEFAULT '{}',
    trend_1h DECIMAL(8,5),
    trend_6h DECIMAL(8,5),
    trend_24h DECIMAL(8,5),
    metadata JSONB DEFAULT '{}',
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_gcs_captured ON global_coherence_snapshots(captured_at);

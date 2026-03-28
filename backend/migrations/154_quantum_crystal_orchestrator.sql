-- Migration 154: Quantum Crystal Orchestrator data model
-- Adds:
--   1) coherence_time_crystals
--   2) crystal_recall_log
--   3) crystal_co_activation_events (idempotent cross-modality co-activation writes)
--   4) crystal_edges enhancements (typed strength/co-activation metadata)
--   5) confidence monotonicity trigger on nate_intelligence_crystals

CREATE TABLE IF NOT EXISTS coherence_time_crystals (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    crystal_ids TEXT[] NOT NULL DEFAULT '{}',
    period_days DOUBLE PRECISION NOT NULL,
    phase_offset_days DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    next_activation_at TIMESTAMPTZ,
    temporal_confidence REAL NOT NULL DEFAULT 0.60,
    activation_count INTEGER NOT NULL DEFAULT 0,
    total_predictions INTEGER NOT NULL DEFAULT 0,
    prediction_accuracy REAL NOT NULL DEFAULT 0.0,
    synthesized_meaning TEXT,
    therapeutic_implication TEXT,
    signal VARCHAR(24) NOT NULL DEFAULT 'PROVISIONAL',
    last_activation_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_time_crystals_user_next_conf
    ON coherence_time_crystals (user_id, next_activation_at, temporal_confidence DESC);

CREATE INDEX IF NOT EXISTS idx_time_crystals_user_active
    ON coherence_time_crystals (user_id, temporal_confidence DESC);

CREATE TABLE IF NOT EXISTS crystal_recall_log (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    crystal_id INTEGER REFERENCES nate_intelligence_crystals(id) ON DELETE CASCADE,
    crystal_hash VARCHAR(64),
    source VARCHAR(64) NOT NULL DEFAULT 'unknown',
    session_id TEXT,
    call_sid TEXT,
    odpe_signal VARCHAR(24),
    recalled_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_crystal_recall_log_user_time
    ON crystal_recall_log (user_id, recalled_at DESC);

CREATE INDEX IF NOT EXISTS idx_crystal_recall_log_crystal_time
    ON crystal_recall_log (crystal_id, recalled_at DESC);

CREATE TABLE IF NOT EXISTS crystal_co_activation_events (
    id BIGSERIAL PRIMARY KEY,
    source VARCHAR(64) NOT NULL,
    session_id TEXT,
    call_sid TEXT,
    crystal_a VARCHAR(64) NOT NULL,
    crystal_b VARCHAR(64) NOT NULL,
    time_bucket TIMESTAMPTZ NOT NULL,
    event_count INTEGER NOT NULL DEFAULT 1,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_co_activation_bucket
    ON crystal_co_activation_events (
        source,
        COALESCE(session_id, ''),
        COALESCE(call_sid, ''),
        crystal_a,
        crystal_b,
        time_bucket
    );

CREATE INDEX IF NOT EXISTS idx_co_activation_events_bucket
    ON crystal_co_activation_events (source, time_bucket DESC);

ALTER TABLE crystal_edges
    ADD COLUMN IF NOT EXISTS crystal_a VARCHAR(64),
    ADD COLUMN IF NOT EXISTS crystal_b VARCHAR(64),
    ADD COLUMN IF NOT EXISTS strength REAL,
    ADD COLUMN IF NOT EXISTS co_activation_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_co_activated_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS source VARCHAR(64) NOT NULL DEFAULT 'legacy';

UPDATE crystal_edges
SET crystal_a = COALESCE(crystal_a, crystal_a_hash),
    crystal_b = COALESCE(crystal_b, crystal_b_hash),
    strength = COALESCE(strength, similarity);

CREATE INDEX IF NOT EXISTS idx_crystal_edges_a_type_strength
    ON crystal_edges (crystal_a, edge_type, strength DESC);

CREATE INDEX IF NOT EXISTS idx_crystal_edges_b_type_strength
    ON crystal_edges (crystal_b, edge_type, strength DESC);

CREATE OR REPLACE FUNCTION prevent_crystal_confidence_decay()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.confidence < OLD.confidence THEN
        RAISE EXCEPTION
            'Crystal confidence decay is prohibited. Crystal % cannot decrease from % to %.',
            OLD.id, OLD.confidence, NEW.confidence;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS no_confidence_decay ON nate_intelligence_crystals;
CREATE TRIGGER no_confidence_decay
    BEFORE UPDATE ON nate_intelligence_crystals
    FOR EACH ROW
    WHEN (NEW.confidence < OLD.confidence)
    EXECUTE FUNCTION prevent_crystal_confidence_decay();

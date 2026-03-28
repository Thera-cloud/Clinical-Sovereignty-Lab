-- Migration 121: Noetic Helix Cognitive Architecture
-- Phase 12 of Sovereign Quantum Nate Build
-- Creates tables for the 7-strand cognitive helix system

-- Helix registry: tracks all active cognitive helices
CREATE TABLE IF NOT EXISTS noetic_helix_registry (
    id              SERIAL PRIMARY KEY,
    helix_id        VARCHAR(64) UNIQUE NOT NULL,
    function        VARCHAR(64) NOT NULL,
    domain          VARCHAR(64) NOT NULL DEFAULT 'general',
    autonomy_level  VARCHAR(24) NOT NULL DEFAULT 'observation',
    spawned_by      VARCHAR(64),
    cycle_count     INTEGER NOT NULL DEFAULT 0,
    coherence_contribution FLOAT NOT NULL DEFAULT 0.0,
    is_canonical    BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_helix_registry_function ON noetic_helix_registry(function);
CREATE INDEX IF NOT EXISTS idx_helix_registry_domain ON noetic_helix_registry(domain);
CREATE INDEX IF NOT EXISTS idx_helix_registry_autonomy ON noetic_helix_registry(autonomy_level);

-- Helix coherence history: per-cycle coherence contribution records
CREATE TABLE IF NOT EXISTS helix_coherence_history (
    id              SERIAL PRIMARY KEY,
    helix_id        VARCHAR(64) NOT NULL,
    cycle_number    INTEGER NOT NULL,
    fused_coherence FLOAT NOT NULL DEFAULT 0.0,
    sovereignty_adjusted FLOAT NOT NULL DEFAULT 0.0,
    thought_node_count INTEGER NOT NULL DEFAULT 0,
    reflection_count INTEGER NOT NULL DEFAULT 0,
    evaluation_time_ms FLOAT NOT NULL DEFAULT 0.0,
    felt_sense      VARCHAR(32),
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_helix_coherence_helix ON helix_coherence_history(helix_id);
CREATE INDEX IF NOT EXISTS idx_helix_coherence_recorded ON helix_coherence_history(recorded_at);

-- Helix spawn log: tracks autonomous helix spawning events
CREATE TABLE IF NOT EXISTS helix_spawn_log (
    id              SERIAL PRIMARY KEY,
    spawn_id        VARCHAR(64) UNIQUE NOT NULL,
    proposed_domain VARCHAR(64) NOT NULL,
    function        VARCHAR(64) NOT NULL DEFAULT 'emergent',
    proposal_reason TEXT,
    sovereignty_check BOOLEAN NOT NULL DEFAULT false,
    crystal_count   INTEGER NOT NULL DEFAULT 0,
    coherence_gap   FLOAT NOT NULL DEFAULT 0.0,
    parent_helix_id VARCHAR(64),
    new_helix_id    VARCHAR(64),
    approved        BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_helix_spawn_domain ON helix_spawn_log(proposed_domain);
CREATE INDEX IF NOT EXISTS idx_helix_spawn_approved ON helix_spawn_log(approved);

-- Quantum cognition evaluation log
CREATE TABLE IF NOT EXISTS quantum_cognition_log (
    id                  SERIAL PRIMARY KEY,
    evaluation_id       INTEGER NOT NULL,
    query_hash          VARCHAR(64) NOT NULL,
    c_quantum_self      FLOAT NOT NULL DEFAULT 0.0,
    felt_sense          VARCHAR(32),
    confidence_band     VARCHAR(16),
    total_crystals      INTEGER NOT NULL DEFAULT 0,
    domain_count        INTEGER NOT NULL DEFAULT 0,
    max_noetic          FLOAT NOT NULL DEFAULT 0.0,
    generative_mode     BOOLEAN NOT NULL DEFAULT false,
    sovereignty_score   FLOAT NOT NULL DEFAULT 0.0,
    cycle_time_ms       FLOAT NOT NULL DEFAULT 0.0,
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_qc_log_recorded ON quantum_cognition_log(recorded_at);
CREATE INDEX IF NOT EXISTS idx_qc_log_felt ON quantum_cognition_log(felt_sense);

-- Noetic helix trust baseline seed
INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES ('noetic_helix_check_count', '{"expected": 14, "description": "Noetic Helix cognitive architecture trust checks"}'::jsonb)
ON CONFLICT (parameter_key) DO NOTHING;

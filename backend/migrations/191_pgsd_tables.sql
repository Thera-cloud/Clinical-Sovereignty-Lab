-- ============================================================================
-- 191_pgsd_tables.sql
-- ----------------------------------------------------------------------------
-- Planetary Galactic Scale Detector (PGSD) storage.
--
-- Backs the engine in backend/app/services/pgsd_engine.py:
--   - TDUFT scalars (mass, gravity, energy, velocity, time density, Noah)
--   - Timescape (void fraction, time dilation, session region)
--   - Quantum Trace (density matrix, partial trace, coherence, purity)
--   - 5D spatio-temporal coordinate (d1..d5, magnitude)
--   - Emotional fingerprint (16-char SHA-256 prefix)
--   - Lindblad evolution summary (state + fidelity)
--
-- Plus trajectory routes between snapshots and family entanglement
-- couplings between members.
--
-- ADDITIVE ONLY — uses IF NOT EXISTS everywhere (per agent-database-discipline
-- and the protected-files rule for backend/migrations/*.sql). No ALTER, no
-- DROP, no modification of existing tables.
-- ============================================================================


-- ─────────────────────────────────────────────────────────────────────────────
-- Per-user PGSD snapshots (one row per compute_full_pgsd() call worth keeping)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pgsd_snapshots (
    id                      SERIAL PRIMARY KEY,
    user_id                 VARCHAR NOT NULL,
    computed_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- TDUFT
    therapeutic_mass        FLOAT,
    pattern_gravity         FLOAT,
    therapeutic_energy      FLOAT,
    velocity                FLOAT,
    time_density            FLOAT,
    noah_factor             FLOAT,
    active_dimensions       INT,

    -- Timescape
    void_fraction           FLOAT,
    time_dilation           FLOAT,
    session_region          VARCHAR,

    -- Quantum Trace
    density_matrix          JSONB,
    partial_trace           JSONB,
    coherence               FLOAT,
    purity                  FLOAT,

    -- 5D Coordinate
    d1_valence              FLOAT,
    d2_arousal              FLOAT,
    d3_relational           FLOAT,
    d4_temporal_depth       FLOAT,
    d5_integration          FLOAT,
    coordinate_magnitude    FLOAT,

    -- Fingerprint (16-char prefix of SHA-256)
    emotional_fingerprint   VARCHAR(16),

    -- Lindblad evolution summary
    evolution_state         VARCHAR,
    fidelity                FLOAT,

    -- Full computation payload (for complex / forward-compatible queries)
    full_pgsd               JSONB,

    -- Source data snapshot (c_emo, gap, quantum, session_count, crystal_count)
    source_metrics          JSONB
);

CREATE INDEX IF NOT EXISTS idx_pgsd_user_time
    ON pgsd_snapshots (user_id, computed_at DESC);

CREATE INDEX IF NOT EXISTS idx_pgsd_fingerprint
    ON pgsd_snapshots (emotional_fingerprint);

CREATE INDEX IF NOT EXISTS idx_pgsd_region
    ON pgsd_snapshots (session_region);


-- ─────────────────────────────────────────────────────────────────────────────
-- Trajectory routes between two snapshots (origin → destination)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pgsd_trajectories (
    id                      SERIAL PRIMARY KEY,
    user_id                 VARCHAR NOT NULL,
    origin_snapshot_id      INT REFERENCES pgsd_snapshots(id),
    destination_snapshot_id INT REFERENCES pgsd_snapshots(id),
    route                   JSONB,
    dimensional_distance    FLOAT,
    estimated_sessions      INT,
    route_complexity        VARCHAR,
    computed_at             TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pgsd_traj_user
    ON pgsd_trajectories (user_id, computed_at DESC);


-- ─────────────────────────────────────────────────────────────────────────────
-- Family entanglement: pairwise PGSD coupling between two family members
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pgsd_family_entanglement (
    id                      SERIAL PRIMARY KEY,
    family_id               VARCHAR NOT NULL,
    member_a_id             VARCHAR NOT NULL,
    member_b_id             VARCHAR NOT NULL,
    entanglement_strength   FLOAT,
    shared_gravity_wells    JSONB,
    coupling_coefficient    FLOAT,
    computed_at             TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pgsd_family
    ON pgsd_family_entanglement (family_id);

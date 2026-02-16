-- ============================================================================
-- Migration 022: Quakete Tables
-- Layer 8 — Collisionless Fibre Trail Emission Protocol
-- Patent Claim 26
-- ============================================================================

-- Cosmic Relational Rings — three-Fibre solidarity topology
CREATE TABLE IF NOT EXISTS cosmic_rings (
    ring_id         VARCHAR(128) PRIMARY KEY,
    cord_1_id       VARCHAR(128) NOT NULL,
    cord_1_type     VARCHAR(32) NOT NULL,
    cord_2_id       VARCHAR(128) NOT NULL,
    cord_2_type     VARCHAR(32) NOT NULL,
    cord_3_id       VARCHAR(128) NOT NULL,
    cord_3_type     VARCHAR(32) NOT NULL,
    ring_coherence  REAL DEFAULT 1.0,
    ring_state      VARCHAR(20) DEFAULT 'healthy'
        CHECK (ring_state IN ('healthy', 'supporting', 'strained',
                              'distressed', 'rescue', 'broken')),
    quakete_events  INTEGER DEFAULT 0,
    formed_at       TIMESTAMPTZ DEFAULT NOW(),
    dissolved_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_cosmic_rings_state
    ON cosmic_rings (ring_state) WHERE dissolved_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_cosmic_rings_cord1
    ON cosmic_rings (cord_1_id) WHERE dissolved_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_cosmic_rings_cord2
    ON cosmic_rings (cord_2_id) WHERE dissolved_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_cosmic_rings_cord3
    ON cosmic_rings (cord_3_id) WHERE dissolved_at IS NULL;

-- Trail emissions — Fibre heartbeat records
CREATE TABLE IF NOT EXISTS trail_emissions (
    id                      BIGSERIAL PRIMARY KEY,
    fibre_id                VARCHAR(128) NOT NULL,
    fibre_type              VARCHAR(32) NOT NULL,
    trail_sequence          INTEGER NOT NULL,
    ambient_ble_density     REAL DEFAULT 0.0,
    fragment_throughput     REAL DEFAULT 0.0,
    observation_queue_depth INTEGER DEFAULT 0,
    time_since_delivery     INTEGER DEFAULT 0,
    communication_health    REAL DEFAULT 1.0,
    quakete_mode            VARCHAR(20) DEFAULT 'nominal'
        CHECK (quakete_mode IN ('nominal', 'surplus', 'requesting',
                                'donating', 'critical', 'silent')),
    surplus_capacity        REAL DEFAULT 0.0,
    deficit_capacity        REAL DEFAULT 0.0,
    resonance_frequency     REAL DEFAULT 0.0,
    ring_id                 VARCHAR(128),
    ring_position           SMALLINT,
    emitted_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trail_emissions_fibre
    ON trail_emissions (fibre_id, emitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_trail_emissions_ring
    ON trail_emissions (ring_id, emitted_at DESC) WHERE ring_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_trail_emissions_mode
    ON trail_emissions (quakete_mode, emitted_at DESC);

-- Quakete transfers — energy transfer events
CREATE TABLE IF NOT EXISTS quakete_transfers (
    id                          BIGSERIAL PRIMARY KEY,
    recipient_id                VARCHAR(128) NOT NULL,
    ring_id                     VARCHAR(128),
    success                     BOOLEAN NOT NULL,
    reason                      TEXT,
    ions_transferred            INTEGER DEFAULT 0,
    total_energy                REAL DEFAULT 0.0,
    detection_boost             REAL DEFAULT 1.0,
    embedding_boost             REAL DEFAULT 1.0,
    assembly_boost              REAL DEFAULT 1.0,
    forwarding_boost            REAL DEFAULT 1.0,
    ring_coherence_after        REAL,
    recovery_seconds_predicted  REAL,
    transferred_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quakete_transfers_recipient
    ON quakete_transfers (recipient_id, transferred_at DESC);

-- Memorials — lost Fibre wisdom preservation
CREATE TABLE IF NOT EXISTS quakete_memorials (
    memorial_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lost_fibre_id   VARCHAR(128) NOT NULL,
    lost_fibre_type VARCHAR(32) NOT NULL,
    lost_at         TIMESTAMPTZ DEFAULT NOW(),
    last_health     REAL DEFAULT 0.0,
    last_mission    TEXT,
    pending_obs     INTEGER DEFAULT 0,
    quaketes_rcvd   INTEGER DEFAULT 0,
    memorial_hash   VARCHAR(128),
    carried_by      VARCHAR(128)[] DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_memorials_lost_fibre
    ON quakete_memorials (lost_fibre_id);

-- Particle beams — directed energy bursts
CREATE TABLE IF NOT EXISTS particle_beams (
    beam_id             VARCHAR(128) PRIMARY KEY,
    target_fibre_id     VARCHAR(128) NOT NULL,
    initial_energy      REAL NOT NULL,
    decay_half_life     INTEGER DEFAULT 300,
    affected_endpoints  TEXT[] DEFAULT '{}',
    fragments_accel     INTEGER DEFAULT 0,
    observations_deliv  INTEGER DEFAULT 0,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    expired_at          TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_particle_beams_target
    ON particle_beams (target_fibre_id) WHERE expired_at IS NULL;

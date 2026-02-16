-- ============================================================================
-- Migration 021: ZEFCP Tables
-- Layer 1 — Zero-Energy Fibre Communication Protocol
-- Patent Claim 25
-- ============================================================================

-- Fragment assemblies — track in-progress observation reassembly
CREATE TABLE IF NOT EXISTS fragment_assemblies (
    id                  BIGSERIAL PRIMARY KEY,
    observation_key     VARCHAR(128) NOT NULL,
    endpoint_id         VARCHAR(64) NOT NULL,
    total_fragments     INTEGER NOT NULL,
    received_fragments  INTEGER NOT NULL DEFAULT 0,
    received_sequences  INTEGER[] DEFAULT '{}',
    is_trail            BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    last_fragment_at    TIMESTAMPTZ DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    assembly_duration_s REAL,
    rs_corrections      INTEGER DEFAULT 0,
    status              VARCHAR(20) DEFAULT 'pending'
        CHECK (status IN ('pending', 'completed', 'expired', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_fragment_assemblies_key
    ON fragment_assemblies (observation_key);
CREATE INDEX IF NOT EXISTS idx_fragment_assemblies_endpoint
    ON fragment_assemblies (endpoint_id);
CREATE INDEX IF NOT EXISTS idx_fragment_assemblies_status
    ON fragment_assemblies (status, created_at);

-- Transport metrics — periodic metrics snapshots per endpoint
CREATE TABLE IF NOT EXISTS transport_metrics (
    id                          BIGSERIAL PRIMARY KEY,
    endpoint_id                 VARCHAR(64) NOT NULL,
    period_start                TIMESTAMPTZ NOT NULL,
    period_end                  TIMESTAMPTZ NOT NULL,
    total_pdus_scanned          INTEGER DEFAULT 0,
    signature_matches           INTEGER DEFAULT 0,
    crc_validated               INTEGER DEFAULT 0,
    false_positives_discarded   INTEGER DEFAULT 0,
    valid_fragments_detected    INTEGER DEFAULT 0,
    observations_completed      INTEGER DEFAULT 0,
    observations_expired        INTEGER DEFAULT 0,
    avg_assembly_time_s         REAL DEFAULT 0.0,
    avg_fragments_per_obs       REAL DEFAULT 0.0,
    avg_fragment_loss_rate      REAL DEFAULT 0.0,
    rs_corrections              INTEGER DEFAULT 0,
    ambient_ble_density         REAL DEFAULT 0.0,
    unique_devices_observed     INTEGER DEFAULT 0,
    fragments_forwarded_cloud   INTEGER DEFAULT 0,
    observations_forwarded_mesh INTEGER DEFAULT 0,
    created_at                  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_transport_metrics_endpoint
    ON transport_metrics (endpoint_id, period_start);

-- Endpoint registry — registered Spider Web endpoints
CREATE TABLE IF NOT EXISTS zefcp_endpoints (
    id              SERIAL PRIMARY KEY,
    endpoint_id     VARCHAR(64) UNIQUE NOT NULL,
    device_id       VARCHAR(128),
    environment     VARCHAR(32) DEFAULT 'unknown',
    avg_density     REAL DEFAULT 0.0,
    domain_tags     TEXT[] DEFAULT '{}',
    config_json     JSONB DEFAULT '{}',
    provisioned_at  TIMESTAMPTZ,
    last_active_at  TIMESTAMPTZ DEFAULT NOW(),
    status          VARCHAR(20) DEFAULT 'active'
        CHECK (status IN ('active', 'inactive', 'provisioning')),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_zefcp_endpoints_status
    ON zefcp_endpoints (status);

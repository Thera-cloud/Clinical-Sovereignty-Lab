-- =============================================================================
-- HIVE DEFENSE PROTOCOL — Foundation Tables (Phase 8A/8B)
-- Patent-Pending — Claims 30-56
-- =============================================================================

-- Forensic logs — immutable append-only evidence chain
CREATE TABLE IF NOT EXISTS hive_forensic_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type      VARCHAR(100) NOT NULL,
    source_entity   VARCHAR(255),
    target_entity   VARCHAR(255),
    evidence        JSONB NOT NULL DEFAULT '{}',
    chain_hash      VARCHAR(64) NOT NULL,
    previous_hash   VARCHAR(64) NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_forensic_event_type ON hive_forensic_logs(event_type);
CREATE INDEX IF NOT EXISTS idx_forensic_created ON hive_forensic_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_forensic_source ON hive_forensic_logs(source_entity);

-- Attacker fingerprints
CREATE TABLE IF NOT EXISTS attacker_fingerprints (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    communication_proto JSONB NOT NULL DEFAULT '{}',
    network_topology    JSONB NOT NULL DEFAULT '{}',
    tool_signatures     TEXT[] NOT NULL DEFAULT '{}',
    behavioral_patterns JSONB NOT NULL DEFAULT '{}',
    sophistication      INT NOT NULL DEFAULT 1,
    working_hours       VARCHAR(100),
    timezone_estimate   VARCHAR(50),
    first_seen          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen           TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_fingerprint_sophistication ON attacker_fingerprints(sophistication);

-- Curiosity events
CREATE TABLE IF NOT EXISTS curiosity_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id       UUID NOT NULL,
    level           VARCHAR(20) NOT NULL,
    divergence_type VARCHAR(100) NOT NULL,
    details         TEXT DEFAULT '',
    ring_notified   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_curiosity_entity ON curiosity_events(entity_id);
CREATE INDEX IF NOT EXISTS idx_curiosity_level ON curiosity_events(level);
CREATE INDEX IF NOT EXISTS idx_curiosity_created ON curiosity_events(created_at);

-- Containment zones
CREATE TABLE IF NOT EXISTS containment_zones (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    zone_name       VARCHAR(255) NOT NULL,
    zone_type       VARCHAR(50) NOT NULL DEFAULT 'standard',  -- standard, recursive_shell
    shell_depth     INT NOT NULL DEFAULT 0,
    entities        TEXT[] NOT NULL DEFAULT '{}',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    topology_fingerprint VARCHAR(128),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deactivated_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_containment_active ON containment_zones(is_active);

-- DEFCON state & history
CREATE TABLE IF NOT EXISTS defcon_state (
    id              SERIAL PRIMARY KEY,
    level           INT NOT NULL DEFAULT 5,
    trigger_reason  TEXT DEFAULT '',
    heartbeat_interval FLOAT NOT NULL DEFAULT 60.0,
    cds_multiplier  FLOAT NOT NULL DEFAULT 1.0,
    max_cert_births INT NOT NULL DEFAULT 50,
    mirror_mode     VARCHAR(20) NOT NULL DEFAULT 'passive',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS defcon_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_level      INT NOT NULL,
    to_level        INT NOT NULL,
    trigger_reason  TEXT DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_defcon_hist_created ON defcon_history(created_at);

-- Cumulative drift scores
CREATE TABLE IF NOT EXISTS drift_scores (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id       UUID NOT NULL UNIQUE,
    data_access     FLOAT NOT NULL DEFAULT 0.0,
    communication   FLOAT NOT NULL DEFAULT 0.0,
    coherence       FLOAT NOT NULL DEFAULT 0.0,
    trail_emission  FLOAT NOT NULL DEFAULT 0.0,
    journal_traj    FLOAT NOT NULL DEFAULT 0.0,
    timing_pattern  FLOAT NOT NULL DEFAULT 0.0,
    combined_mag    FLOAT NOT NULL DEFAULT 0.0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_drift_entity ON drift_scores(entity_id);
CREATE INDEX IF NOT EXISTS idx_drift_magnitude ON drift_scores(combined_mag);

-- Content Sentinel verdicts
CREATE TABLE IF NOT EXISTS content_sentinel_verdicts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_id       UUID NOT NULL,
    verdict         VARCHAR(30) NOT NULL,
    checks          JSONB NOT NULL DEFAULT '{}',
    entropy_score   FLOAT NOT NULL DEFAULT 0.0,
    injection_flag  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sentinel_verdict ON content_sentinel_verdicts(verdict);

-- Ghost missions
CREATE TABLE IF NOT EXISTS ghost_missions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    containment_zone VARCHAR(255) NOT NULL,
    ghost_count     INT NOT NULL DEFAULT 7,
    ghosts          JSONB NOT NULL DEFAULT '[]',
    status          VARCHAR(30) NOT NULL DEFAULT 'active',
    deployed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

-- Canary access events
CREATE TABLE IF NOT EXISTS canary_access_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canary_id       UUID NOT NULL,
    credential_type VARCHAR(50) NOT NULL,
    access_source   VARCHAR(255),
    accessed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_canary_accessed ON canary_access_events(accessed_at);

-- Birth rate events
CREATE TABLE IF NOT EXISTS birth_rate_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type      VARCHAR(50) NOT NULL,  -- normal, anomaly, paused
    births_in_window INT NOT NULL DEFAULT 0,
    window_minutes  INT NOT NULL DEFAULT 60,
    source_ip       VARCHAR(50),
    cert_id         UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Quarantine state
CREATE TABLE IF NOT EXISTS quarantine_state (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fibre_id        UUID NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    duration_min    INT NOT NULL DEFAULT 60,
    heartbeat_ok    BOOLEAN NOT NULL DEFAULT FALSE,
    access_ok       BOOLEAN NOT NULL DEFAULT FALSE,
    ring_ok         BOOLEAN NOT NULL DEFAULT FALSE,
    trail_ok        BOOLEAN NOT NULL DEFAULT FALSE,
    passed          BOOLEAN,
    evaluated_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_quarantine_fibre ON quarantine_state(fibre_id);

-- Behavioral snapshots
CREATE TABLE IF NOT EXISTS behavioral_snapshots (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id       UUID NOT NULL,
    week_number     INT NOT NULL,
    data_access_hash    VARCHAR(64),
    comm_graph_hash     VARCHAR(64),
    trail_fingerprint   VARCHAR(64),
    coherence_hash      VARCHAR(64),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_snapshot_entity ON behavioral_snapshots(entity_id);
CREATE INDEX IF NOT EXISTS idx_snapshot_week ON behavioral_snapshots(week_number);

-- Conservation ledger
CREATE TABLE IF NOT EXISTS conservation_ledger (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    total_energy    FLOAT NOT NULL,
    ledger_hash     VARCHAR(64) NOT NULL,
    violations      INT NOT NULL DEFAULT 0,
    is_valid        BOOLEAN NOT NULL DEFAULT TRUE,
    verified_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Tripwire activations
CREATE TABLE IF NOT EXISTS tripwire_activations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tripwire_type   VARCHAR(50) NOT NULL,
    containment_zone VARCHAR(255),
    triggered_by    VARCHAR(255),
    evidence        JSONB NOT NULL DEFAULT '{}',
    triggered_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Projected Helix deployments
CREATE TABLE IF NOT EXISTS projected_helix_deployments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_profile  UUID NOT NULL REFERENCES attacker_fingerprints(id),
    penetrator_report JSONB NOT NULL DEFAULT '{}',
    status          VARCHAR(30) NOT NULL DEFAULT 'pending_auth',
    authorized_by   VARCHAR(255),
    authorized_at   TIMESTAMPTZ,
    deployed_at     TIMESTAMPTZ,
    mirror_accuracy FLOAT NOT NULL DEFAULT 0.7,
    interactions    INT NOT NULL DEFAULT 0,
    commands_intercepted INT NOT NULL DEFAULT 0,
    intelligence    JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Inverted spaces (triangular mirror traps)
CREATE TABLE IF NOT EXISTS inverted_spaces (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attacker_fp_id  UUID REFERENCES attacker_fingerprints(id),
    entry_gate      VARCHAR(100),
    helix_state     JSONB NOT NULL DEFAULT '[]',
    interaction_count INT NOT NULL DEFAULT 0,
    tripwires_triggered INT NOT NULL DEFAULT 0,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed initial DEFCON state at PEACE
INSERT INTO defcon_state (level, trigger_reason, heartbeat_interval, cds_multiplier, max_cert_births, mirror_mode)
SELECT 5, 'System initialized', 60.0, 1.0, 50, 'passive'
WHERE NOT EXISTS (SELECT 1 FROM defcon_state LIMIT 1);

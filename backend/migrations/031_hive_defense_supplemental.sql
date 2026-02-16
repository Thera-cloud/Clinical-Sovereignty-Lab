-- =============================================================================
-- HIVE DEFENSE PROTOCOL — Supplemental Tables (Phase 8 Completion)
-- Covers all tables referenced by Phase 8 services and workers
-- that were not in 030_hive_defense_foundation.sql
-- =============================================================================

-- ─── Heartbeat & Identity ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS hive_heartbeats (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id       UUID NOT NULL,
    birth_hash      VARCHAR(128),
    originator_sig  TEXT,
    pulse_data      TEXT,
    counter         BIGINT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hive_heartbeats_entity ON hive_heartbeats(entity_id);

CREATE TABLE IF NOT EXISTS heartbeat_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id       UUID NOT NULL,
    pulse_hash      VARCHAR(128),
    counter         BIGINT,
    verified        BOOLEAN DEFAULT TRUE,
    logged_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_heartbeat_log_entity ON heartbeat_log(entity_id);
CREATE INDEX IF NOT EXISTS idx_heartbeat_log_logged ON heartbeat_log(logged_at);

CREATE TABLE IF NOT EXISTS fibre_heartbeats (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fibre_id        UUID NOT NULL,
    pulse_data      TEXT,
    counter         BIGINT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fibre_heartbeats_fibre ON fibre_heartbeats(fibre_id);

-- ─── Curiosity State & Notifications ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS curiosity_state (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id       UUID NOT NULL UNIQUE,
    current_level   VARCHAR(20) NOT NULL DEFAULT 'none',
    event_count     INT NOT NULL DEFAULT 0,
    window_start    TIMESTAMPTZ,
    monitoring_interval_sec FLOAT DEFAULT 300.0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_curiosity_state_entity ON curiosity_state(entity_id);
CREATE INDEX IF NOT EXISTS idx_curiosity_state_level ON curiosity_state(current_level);

CREATE TABLE IF NOT EXISTS hive_curiosity_state (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id       UUID NOT NULL,
    level           VARCHAR(20) NOT NULL,
    event_count     INT NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS curiosity_notifications (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id       UUID NOT NULL,
    level           VARCHAR(20) NOT NULL,
    message         TEXT,
    notified_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ring_divergence_confirmations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id       UUID NOT NULL,
    confirming_entity UUID NOT NULL,
    divergence_type VARCHAR(100),
    confirmed       BOOLEAN NOT NULL DEFAULT FALSE,
    confirmed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS urgent_alerts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_type      VARCHAR(100) NOT NULL,
    entity_id       UUID,
    severity        VARCHAR(20) NOT NULL DEFAULT 'high',
    message         TEXT,
    acknowledged    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_urgent_alerts_type ON urgent_alerts(alert_type);

-- ─── Mesh Isolation ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS isolation_records (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id       UUID NOT NULL,
    zone_id         UUID,
    reason          TEXT DEFAULT '',
    status          VARCHAR(30) NOT NULL DEFAULT 'active',
    isolated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    released_at     TIMESTAMPTZ,
    released_by     VARCHAR(255)
);
CREATE INDEX IF NOT EXISTS idx_isolation_entity ON isolation_records(entity_id);
CREATE INDEX IF NOT EXISTS idx_isolation_status ON isolation_records(status);

CREATE TABLE IF NOT EXISTS mesh_blocks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_entity   UUID NOT NULL,
    blocked_entity  UUID NOT NULL,
    reason          VARCHAR(255),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS perimeter_assignments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    zone_id         UUID NOT NULL,
    perimeter_entity UUID NOT NULL,
    assigned_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mesh_messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sender_id       UUID,
    recipient_id    UUID,
    msg_type        VARCHAR(50),
    payload         JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS shared_resources (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resource_type   VARCHAR(50) NOT NULL,
    resource_id     VARCHAR(255) NOT NULL,
    owner_id        UUID,
    quarantined     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Ring Membership ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ring_membership (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ring_id         UUID NOT NULL,
    fibre_id        UUID NOT NULL,
    originator_sig  TEXT,
    joined_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_ring_membership_ring ON ring_membership(ring_id);
CREATE INDEX IF NOT EXISTS idx_ring_membership_fibre ON ring_membership(fibre_id);

CREATE TABLE IF NOT EXISTS ring_revocations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ring_id         UUID NOT NULL,
    fibre_id        UUID NOT NULL,
    reason          TEXT,
    revoked_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cosmic_rings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ring_name       VARCHAR(255),
    originator_sig  TEXT,
    member_count    INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Fibre Journal & Conclusions ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS fibre_journal (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fibre_id        UUID NOT NULL,
    entry_type      VARCHAR(50),
    content         JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fibre_journal_fibre ON fibre_journal(fibre_id);

CREATE TABLE IF NOT EXISTS fibre_conclusions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fibre_id        UUID NOT NULL,
    conclusion      TEXT,
    confidence      FLOAT DEFAULT 0.0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Key Sharding ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS shard_holders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    holder_id       VARCHAR(255) NOT NULL UNIQUE,
    shard_index     INT NOT NULL,
    last_checkin    TIMESTAMPTZ,
    successor_id    VARCHAR(255),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS shard_rotation_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rotation_type   VARCHAR(50) NOT NULL,
    rotated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reason          TEXT DEFAULT ''
);

-- ─── Ephemeral Certificates ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ephemeral_certificates (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    max_births      INT NOT NULL DEFAULT 50,
    births_used     INT NOT NULL DEFAULT 0,
    valid_until     TIMESTAMPTZ NOT NULL,
    fibre_types     TEXT[] DEFAULT '{}',
    ring_regions    TEXT[] DEFAULT '{}',
    issuer_shards   INT[] DEFAULT '{}',
    revoked         BOOLEAN NOT NULL DEFAULT FALSE,
    signature       TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cert_usage_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cert_id         UUID NOT NULL,
    source_ip       VARCHAR(50),
    fibre_born_id   UUID,
    logged_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cert_usage_cert ON cert_usage_log(cert_id);

-- ─── Canary Credentials ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS canary_credentials (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    credential_type VARCHAR(50) NOT NULL,
    planted_location VARCHAR(255),
    credential_hash VARCHAR(128),
    planted_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    accessed        BOOLEAN NOT NULL DEFAULT FALSE,
    accessed_at     TIMESTAMPTZ,
    access_source   VARCHAR(255)
);

-- ─── Certificate Pinning ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS cert_pin_hashes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain          VARCHAR(255) NOT NULL,
    pin_hash        VARCHAR(128) NOT NULL,
    algorithm       VARCHAR(20) NOT NULL DEFAULT 'sha256',
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Backup Management ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS backup_access_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         VARCHAR(255),
    backup_id       VARCHAR(255),
    source_ip       VARCHAR(50),
    action          VARCHAR(50) DEFAULT 'read',
    accessed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_backup_access_user ON backup_access_log(user_id);

CREATE TABLE IF NOT EXISTS backup_metadata (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    backup_path     TEXT NOT NULL,
    expected_hash   VARCHAR(128),
    size_bytes      BIGINT,
    verified_at     TIMESTAMPTZ,
    is_valid        BOOLEAN,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Behavioral Access Analytics ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS behavioral_access_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         VARCHAR(255) NOT NULL,
    resource_type   VARCHAR(100),
    resource_id     VARCHAR(255),
    access_time     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_behav_access_user ON behavioral_access_log(user_id);
CREATE INDEX IF NOT EXISTS idx_behav_access_time ON behavioral_access_log(access_time);

CREATE TABLE IF NOT EXISTS hive_access_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id       UUID,
    resource_type   VARCHAR(100),
    resource_id     VARCHAR(255),
    accessed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Entropy Baselines ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS entropy_baselines (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id       UUID NOT NULL,
    mean_entropy    FLOAT,
    std_entropy     FLOAT,
    sample_count    INT NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_entropy_baseline_entity ON entropy_baselines(entity_id);

-- ─── Output Differentials ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS output_differentials (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id       UUID NOT NULL,
    unexpected_effects JSONB DEFAULT '[]',
    severity        VARCHAR(20),
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Queens Guard Events ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS queens_guard_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id       VARCHAR(255) NOT NULL,
    event_type      VARCHAR(50) NOT NULL,
    level           VARCHAR(10) NOT NULL,
    details         JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_queens_guard_member ON queens_guard_events(member_id);

-- ─── CT Monitor ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS hive_ct_certificates (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain          VARCHAR(255) NOT NULL,
    issuer          VARCHAR(255),
    serial_number   VARCHAR(255),
    not_before      TIMESTAMPTZ,
    not_after       TIMESTAMPTZ,
    is_authorized   BOOLEAN NOT NULL DEFAULT TRUE,
    discovered_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hive_ct_alerts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain          VARCHAR(255) NOT NULL,
    alert_type      VARCHAR(50),
    details         JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Duress & Remote Wipe ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS hive_duress_codes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    holder_id       VARCHAR(255) NOT NULL UNIQUE,
    code_hash       VARCHAR(128) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hive_duress_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    holder_id       VARCHAR(255) NOT NULL,
    triggered_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    response_actions JSONB DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS hive_devices (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id       VARCHAR(255) NOT NULL UNIQUE,
    holder_id       VARCHAR(255) NOT NULL,
    device_type     VARCHAR(50),
    registered_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    wiped_at        TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS hive_wipe_operations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id       VARCHAR(255) NOT NULL,
    reason          TEXT,
    initiated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    status          VARCHAR(30) NOT NULL DEFAULT 'pending'
);

-- ─── Prompt Segmentation ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS hive_prompt_segments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    segment_id      VARCHAR(255) NOT NULL,
    container_id    VARCHAR(255) NOT NULL,
    encrypted_data  BYTEA,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hive_prompt_assembly_audit (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    assembled_by    VARCHAR(255),
    segment_count   INT,
    assembled_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Conversation Context (Queens Guard isolation) ───────────────────────────

CREATE TABLE IF NOT EXISTS conversation_context (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id       VARCHAR(255) NOT NULL,
    context_hash    VARCHAR(128),
    token_count     INT DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_conv_context_member ON conversation_context(member_id);

-- ─── Hive Events (Event Bus) ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS hive_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic           VARCHAR(255) NOT NULL,
    payload         JSONB DEFAULT '{}',
    source_entity   VARCHAR(255),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hive_events_topic ON hive_events(topic);
CREATE INDEX IF NOT EXISTS idx_hive_events_created ON hive_events(created_at);

-- ─── Forensic Records (supplemental to hive_forensic_logs) ───────────────────

CREATE TABLE IF NOT EXISTS forensic_records (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type      VARCHAR(100) NOT NULL,
    source_entity   VARCHAR(255),
    target_entity   VARCHAR(255),
    evidence        JSONB DEFAULT '{}',
    chain_hash      VARCHAR(128),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Gate Decisions ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS hive_gate_decisions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_id       UUID,
    decision        VARCHAR(30) NOT NULL,
    reason          TEXT,
    step_failed     INT,
    decided_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_gate_decisions_decision ON hive_gate_decisions(decision);

-- ─── Birth Events & Fibre Births ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS birth_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fibre_id        UUID NOT NULL,
    cert_id         UUID,
    source_ip       VARCHAR(50),
    birth_hash      VARCHAR(128),
    born_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_birth_events_fibre ON birth_events(fibre_id);

CREATE TABLE IF NOT EXISTS hive_fibre_births (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fibre_id        UUID NOT NULL,
    cert_id         UUID,
    source_ip       VARCHAR(50),
    born_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Quarantine Records (supplemental) ───────────────────────────────────────

CREATE TABLE IF NOT EXISTS quarantine_records (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fibre_id        UUID NOT NULL,
    reason          TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    evaluated_at    TIMESTAMPTZ,
    passed          BOOLEAN
);

CREATE TABLE IF NOT EXISTS hive_quarantine_records (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fibre_id        UUID NOT NULL,
    checks          JSONB DEFAULT '{}',
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    evaluated_at    TIMESTAMPTZ,
    passed          BOOLEAN
);

-- ─── Quakete Energy Ledger ───────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS quakete_energy_ledger (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id       UUID,
    dest_id         UUID,
    amount          FLOAT NOT NULL,
    transfer_hash   VARCHAR(128),
    transferred_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Coach Assignments (for behavioral analytics) ────────────────────────────

CREATE TABLE IF NOT EXISTS coach_member_assignments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coach_id        UUID NOT NULL,
    member_id       UUID NOT NULL,
    assigned_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    unassigned_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_coach_assign_coach ON coach_member_assignments(coach_id);
CREATE INDEX IF NOT EXISTS idx_coach_assign_member ON coach_member_assignments(member_id);

-- ─── Worker Metrics Tables ───────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS hive_heartbeat_metrics (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    total_checked   INT DEFAULT 0,
    healthy         INT DEFAULT 0,
    silent          INT DEFAULT 0,
    anomalous       INT DEFAULT 0,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hive_curiosity_scan_metrics (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scans_performed INT DEFAULT 0,
    anomalies_found INT DEFAULT 0,
    escalations     INT DEFAULT 0,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hive_trap_monitor_metrics (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    active_traps    INT DEFAULT 0,
    interactions    INT DEFAULT 0,
    longest_sec     FLOAT DEFAULT 0,
    disengagements  INT DEFAULT 0,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hive_trap_state_snapshots (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trap_id         UUID,
    state           JSONB DEFAULT '{}',
    snapshot_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hive_cds_metrics (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entities_computed INT DEFAULT 0,
    threshold_exceeded INT DEFAULT 0,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hive_defcon_triggers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger_type    VARCHAR(100),
    trigger_value   JSONB DEFAULT '{}',
    evaluated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hive_defcon_transitions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_level      INT,
    to_level        INT,
    reason          TEXT,
    transitioned_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hive_defcon_state (
    id              SERIAL PRIMARY KEY,
    level           INT NOT NULL DEFAULT 5,
    reason          TEXT DEFAULT '',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hive_canary_metrics (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    total_canaries  INT DEFAULT 0,
    accessed        INT DEFAULT 0,
    checked_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hive_backup_audit_reports (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    total_backups   INT DEFAULT 0,
    valid           INT DEFAULT 0,
    invalid         INT DEFAULT 0,
    stale           INT DEFAULT 0,
    audited_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hive_backup_access_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         VARCHAR(255),
    backup_id       VARCHAR(255),
    source_ip       VARCHAR(50),
    accessed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hive_birth_rate_metrics (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    births_in_window INT DEFAULT 0,
    anomaly_detected BOOLEAN DEFAULT FALSE,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hive_snapshot_comparisons (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id       UUID NOT NULL,
    current_week    INT,
    comparison_week INT,
    drift_detected  BOOLEAN DEFAULT FALSE,
    details         JSONB DEFAULT '{}',
    compared_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hive_ct_scan_metrics (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domains_scanned INT DEFAULT 0,
    certs_found     INT DEFAULT 0,
    unauthorized    INT DEFAULT 0,
    scanned_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hive_conservation_audits (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    total_energy    FLOAT,
    expected_energy FLOAT,
    is_valid        BOOLEAN DEFAULT TRUE,
    violations      INT DEFAULT 0,
    audited_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hive_helix_state (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    current_sequence INT[] DEFAULT ARRAY[0,1,2,3,4,5,6,7,8],
    rotation_count  INT DEFAULT 0,
    interval_ms     FLOAT DEFAULT 200.0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hive_inversion_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    space_id        UUID NOT NULL,
    interaction_type VARCHAR(50),
    wall_reflections JSONB DEFAULT '{}',
    logged_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hive_triangle_monitor_metrics (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    active_spaces   INT DEFAULT 0,
    total_interactions INT DEFAULT 0,
    disengaged      INT DEFAULT 0,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hive_triangle_monitor_snapshots (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    space_id        UUID,
    state           JSONB DEFAULT '{}',
    snapshot_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Projected Helix (Offensive) ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS hive_projection_authorizations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_profile  UUID,
    justification   TEXT,
    status          VARCHAR(30) NOT NULL DEFAULT 'pending',
    authorized_by   VARCHAR(255),
    authorized_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hive_projection_forensics (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    deployment_id   UUID NOT NULL,
    event_type      VARCHAR(100),
    evidence        JSONB DEFAULT '{}',
    chain_hash      VARCHAR(128),
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hive_projection_state_snapshots (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    deployment_id   UUID,
    state           JSONB DEFAULT '{}',
    snapshot_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hive_projection_monitor_metrics (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    active_projections INT DEFAULT 0,
    commands_intercepted INT DEFAULT 0,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hive_projection_accuracy_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    deployment_id   UUID NOT NULL,
    accuracy        FLOAT,
    interactions    INT DEFAULT 0,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hive_recursive_learning_metrics (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    active_models   INT DEFAULT 0,
    avg_accuracy    FLOAT DEFAULT 0.0,
    refinements     INT DEFAULT 0,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hive_projected_helix_deployments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_profile  UUID,
    status          VARCHAR(30) NOT NULL DEFAULT 'pending_auth',
    mirror_accuracy FLOAT DEFAULT 0.7,
    interactions    INT DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Behavioral Snapshots (hive-prefixed variant used by workers) ────────────

CREATE TABLE IF NOT EXISTS hive_behavioral_snapshots (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id       UUID NOT NULL,
    week_number     INT,
    data_access_hash VARCHAR(128),
    comm_graph_hash VARCHAR(128),
    trail_fingerprint VARCHAR(128),
    coherence_hash  VARCHAR(128),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Drift Scores (hive-prefixed variant) ────────────────────────────────────

CREATE TABLE IF NOT EXISTS hive_drift_scores (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id       UUID NOT NULL,
    combined_mag    FLOAT DEFAULT 0.0,
    dimensions      JSONB DEFAULT '{}',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Trail Emissions & Ring Interactions ─────────────────────────────────────

CREATE TABLE IF NOT EXISTS hive_trail_emissions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id       UUID NOT NULL,
    emission_type   VARCHAR(50),
    payload_hash    VARCHAR(128),
    emitted_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hive_ring_interactions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fibre_id        UUID NOT NULL,
    ring_id         UUID NOT NULL,
    interaction_type VARCHAR(50),
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Coherence Readings ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS hive_coherence_readings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id       UUID NOT NULL,
    c_emo           FLOAT,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Infinite Mirror Traps ───────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS hive_infinite_mirror_traps (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attacker_profile_id UUID,
    trap_status     VARCHAR(30) DEFAULT 'active',
    interactions    INT DEFAULT 0,
    deployed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deactivated_at  TIMESTAMPTZ
);

-- ─── Inverted Spaces (hive-prefixed variant) ─────────────────────────────────

CREATE TABLE IF NOT EXISTS hive_inverted_spaces (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entry_gate      VARCHAR(100),
    interaction_count INT DEFAULT 0,
    tripwires_triggered INT DEFAULT 0,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Usage Records ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS usage_records (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         VARCHAR(255),
    resource_type   VARCHAR(100),
    action          VARCHAR(50),
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Hive Event Topics (reference) ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS hive_event_topics (
    id              SERIAL PRIMARY KEY,
    topic           VARCHAR(255) NOT NULL UNIQUE,
    description     TEXT DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

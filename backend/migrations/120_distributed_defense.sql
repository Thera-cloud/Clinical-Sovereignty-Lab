-- Migration 120: Distributed Defense + Device Reputation + Mesh State
-- Supports Phases 6.6, 8.2, 8.8 of Sovereign Quantum Nate Build

-- Device reputation tracking (Phase 6.6)
CREATE TABLE IF NOT EXISTS device_reputation (
    device_id TEXT PRIMARY KEY,
    submission_count INTEGER DEFAULT 0,
    rejection_count INTEGER DEFAULT 0,
    accepted_count INTEGER DEFAULT 0,
    reputation_score FLOAT DEFAULT 1.0,
    quarantined BOOLEAN DEFAULT FALSE,
    last_activity TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_device_rep_score ON device_reputation(reputation_score);
CREATE INDEX IF NOT EXISTS idx_device_rep_quarantine ON device_reputation(quarantined) WHERE quarantined = TRUE;

-- Mesh curiosity state (Phase 8.2)
CREATE TABLE IF NOT EXISTS mesh_curiosity_state (
    id SERIAL PRIMARY KEY,
    node_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    curiosity_level INTEGER DEFAULT 0,
    signal_count INTEGER DEFAULT 0,
    escalated_at TIMESTAMPTZ,
    last_signal_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(node_id, source_id)
);

CREATE INDEX IF NOT EXISTS idx_mesh_curiosity_level ON mesh_curiosity_state(curiosity_level);
CREATE INDEX IF NOT EXISTS idx_mesh_curiosity_node ON mesh_curiosity_state(node_id);

-- Canary crystal registry (Phase 8.8)
CREATE TABLE IF NOT EXISTS canary_crystals (
    canary_id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    planted_at TIMESTAMPTZ DEFAULT NOW(),
    detected_outside BOOLEAN DEFAULT FALSE,
    detected_at TIMESTAMPTZ,
    exfiltration_source TEXT
);

CREATE INDEX IF NOT EXISTS idx_canary_hash ON canary_crystals(content_hash);
CREATE INDEX IF NOT EXISTS idx_canary_device ON canary_crystals(device_id);

-- Mesh recon reports (Phase 8.9)
CREATE TABLE IF NOT EXISTS mesh_recon_reports (
    id TEXT PRIMARY KEY,
    trigger TEXT NOT NULL,
    defcon_level INTEGER NOT NULL,
    affected_nodes TEXT[],
    node_count INTEGER DEFAULT 0,
    curiosity_summary JSONB,
    canary_alerts JSONB,
    recommendations TEXT[],
    assembled_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_recon_assembled ON mesh_recon_reports(assembled_at);
CREATE INDEX IF NOT EXISTS idx_recon_defcon ON mesh_recon_reports(defcon_level);

-- Crystal replication tracking (Phase 9.5)
CREATE TABLE IF NOT EXISTS crystal_replication (
    crystal_hash TEXT NOT NULL,
    device_id TEXT NOT NULL,
    replicated_at TIMESTAMPTZ DEFAULT NOW(),
    verified BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (crystal_hash, device_id)
);

CREATE INDEX IF NOT EXISTS idx_crystal_rep_hash ON crystal_replication(crystal_hash);

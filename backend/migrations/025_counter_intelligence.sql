-- =============================================================================
-- Migration 025: Counter-Intelligence Tables
-- Phase 8: Sovereign Counter-Intelligence — Reverse Osmosis Defense
-- =============================================================================

-- Attacker profiles — composite fingerprints of suspected attackers
CREATE TABLE IF NOT EXISTS attacker_profiles (
    profile_id UUID PRIMARY KEY,
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    threat_level VARCHAR(20) NOT NULL DEFAULT 'low',
    attack_type VARCHAR(50),
    ble_fingerprint JSONB DEFAULT '{}'::jsonb,
    network_fingerprint JSONB DEFAULT '{}'::jsonb,
    behavioral_fingerprint JSONB DEFAULT '{}'::jsonb,
    infrastructure_map JSONB DEFAULT '{}'::jsonb,
    status VARCHAR(20) DEFAULT 'active'
);

CREATE INDEX IF NOT EXISTS idx_attacker_profiles_status
    ON attacker_profiles(status);
CREATE INDEX IF NOT EXISTS idx_attacker_profiles_threat_level
    ON attacker_profiles(threat_level);
CREATE INDEX IF NOT EXISTS idx_attacker_profiles_last_seen
    ON attacker_profiles(last_seen DESC);

-- Attack events — every detected attack signal with full forensic data
CREATE TABLE IF NOT EXISTS attack_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID REFERENCES attacker_profiles(profile_id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL,
    event_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_layer VARCHAR(20),
    target_fibre_id VARCHAR(50),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_attack_events_profile
    ON attack_events(profile_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_attack_events_occurred
    ON attack_events(occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_attack_events_source
    ON attack_events(source_layer);

-- Canary tokens — tracking markers embedded in decoy data
CREATE TABLE IF NOT EXISTS canary_tokens (
    canary_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canary_type VARCHAR(20) NOT NULL,
    target_attacker UUID REFERENCES attacker_profiles(profile_id) ON DELETE SET NULL,
    payload_hash VARCHAR(64),
    deployed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    triggered_at TIMESTAMPTZ,
    trigger_data JSONB
);

CREATE INDEX IF NOT EXISTS idx_canary_tokens_type
    ON canary_tokens(canary_type);
CREATE INDEX IF NOT EXISTS idx_canary_tokens_triggered
    ON canary_tokens(triggered_at)
    WHERE triggered_at IS NOT NULL;

-- Retrieval seeds — payloads designed to map attacker infrastructure
CREATE TABLE IF NOT EXISTS retrieval_seeds (
    seed_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    seed_type VARCHAR(20) NOT NULL,
    target_attacker UUID REFERENCES attacker_profiles(profile_id) ON DELETE SET NULL,
    deployed_via VARCHAR(20),
    deployed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activation_count INT DEFAULT 0,
    last_activation TIMESTAMPTZ,
    intelligence JSONB DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_retrieval_seeds_type
    ON retrieval_seeds(seed_type);
CREATE INDEX IF NOT EXISTS idx_retrieval_seeds_active
    ON retrieval_seeds(activation_count DESC)
    WHERE activation_count > 0;

-- Counter-measure effectiveness log
CREATE TABLE IF NOT EXISTS counter_measure_log (
    log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attacker_id UUID REFERENCES attacker_profiles(profile_id) ON DELETE SET NULL,
    measure_type VARCHAR(50) NOT NULL,
    deployed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    effectiveness_score FLOAT,
    result JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_counter_measure_attacker
    ON counter_measure_log(attacker_id, deployed_at DESC);

-- Threat signatures — shared across the swarm for distributed detection
CREATE TABLE IF NOT EXISTS threat_signatures (
    signature_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signature_type VARCHAR(30) NOT NULL,
    signature_data JSONB NOT NULL,
    source_profile UUID REFERENCES attacker_profiles(profile_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    active BOOLEAN DEFAULT true
);

CREATE INDEX IF NOT EXISTS idx_threat_signatures_active
    ON threat_signatures(active, signature_type)
    WHERE active = true;

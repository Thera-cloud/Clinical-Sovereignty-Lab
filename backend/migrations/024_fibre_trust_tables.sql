-- =============================================================================
-- Migration 024: Fibre Trust Tables
-- Sovereign Immunity — Fibre trust scoring, violation tracking, and
-- Ed25519 public key registry for identity verification.
-- =============================================================================

-- Fibre trust levels — tracks per-Fibre trust score on a 0-4 scale
-- 0=UNTRUSTED, 1=PROVISIONED, 2=VALIDATED, 3=TRUSTED, 4=CORE
CREATE TABLE IF NOT EXISTS fibre_trust_levels (
    fibre_id UUID PRIMARY KEY REFERENCES fibres(fibre_id) ON DELETE CASCADE,
    trust_level INT NOT NULL DEFAULT 0
        CHECK (trust_level >= 0 AND trust_level <= 4),
    trust_label VARCHAR(20) NOT NULL DEFAULT 'untrusted'
        CHECK (trust_label IN ('untrusted', 'provisioned', 'validated', 'trusted', 'core')),
    good_behavior_count INT NOT NULL DEFAULT 0,
    violation_count INT NOT NULL DEFAULT 0,
    last_promotion_at TIMESTAMPTZ,
    last_violation_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fibre_trust_level
    ON fibre_trust_levels(trust_level);

-- Fibre trust violations — logs every trust violation with severity
CREATE TABLE IF NOT EXISTS fibre_trust_violations (
    violation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fibre_id UUID NOT NULL REFERENCES fibres(fibre_id) ON DELETE CASCADE,
    violation_type VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL DEFAULT 'medium'
        CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    description TEXT,
    trust_level_before INT,
    trust_level_after INT,
    forensic_data JSONB DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fibre_trust_violations_fibre
    ON fibre_trust_violations(fibre_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_fibre_trust_violations_severity
    ON fibre_trust_violations(severity, occurred_at DESC);

-- Fibre public keys — Ed25519 public key registry for identity verification
-- Each Fibre's public key is registered at provisioning and used to verify
-- observation signatures before they enter the Wisdom Mesh.
CREATE TABLE IF NOT EXISTS fibre_public_keys (
    key_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fibre_id UUID NOT NULL REFERENCES fibres(fibre_id) ON DELETE CASCADE,
    public_key BYTEA NOT NULL,
    key_algorithm VARCHAR(20) NOT NULL DEFAULT 'Ed25519',
    provisioned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at TIMESTAMPTZ,
    revocation_reason TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true
);

CREATE INDEX IF NOT EXISTS idx_fibre_public_keys_fibre
    ON fibre_public_keys(fibre_id)
    WHERE is_active = true;
CREATE UNIQUE INDEX IF NOT EXISTS idx_fibre_public_keys_active_unique
    ON fibre_public_keys(fibre_id)
    WHERE is_active = true AND revoked_at IS NULL;

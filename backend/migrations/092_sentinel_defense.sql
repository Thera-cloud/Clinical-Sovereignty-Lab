-- Migration 092: Sentinel Defense — House of Mirrors Wiring
-- Tables for persistent IP banning, freeze forensics, and Helix authorization

-- Persistent IP ban list (survives container restarts)
CREATE TABLE IF NOT EXISTS sentinel_banned_ips (
    id              SERIAL PRIMARY KEY,
    ip              VARCHAR(45) NOT NULL,
    reason          TEXT NOT NULL DEFAULT '',
    banned_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    banned_by       VARCHAR(50) NOT NULL DEFAULT 'sentinel',
    expires_at      TIMESTAMPTZ,
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    attacker_profile JSONB DEFAULT '{}',
    sentinel_score  INTEGER DEFAULT 0,
    UNIQUE(ip)
);

CREATE INDEX IF NOT EXISTS idx_sentinel_banned_active ON sentinel_banned_ips(ip) WHERE active = TRUE;

-- Forensic log of every Sentinel freeze event
CREATE TABLE IF NOT EXISTS sentinel_freeze_history (
    id              SERIAL PRIMARY KEY,
    ip              VARCHAR(45) NOT NULL,
    uid             VARCHAR(100) NOT NULL DEFAULT '',
    user_agent      TEXT DEFAULT '',
    sentinel_score  INTEGER NOT NULL DEFAULT 0,
    reasons         JSONB NOT NULL DEFAULT '[]',
    actions_taken   JSONB NOT NULL DEFAULT '[]',
    defcon_level    INTEGER DEFAULT 5,
    attacker_profile JSONB DEFAULT '{}',
    mirror_namespace_id VARCHAR(36),
    trap_id         VARCHAR(36),
    frozen_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    disengaged_at   TIMESTAMPTZ,
    interactions_mirrored INTEGER DEFAULT 0,
    recon_report_sent BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_sentinel_freeze_frozen_at ON sentinel_freeze_history(frozen_at DESC);
CREATE INDEX IF NOT EXISTS idx_sentinel_freeze_ip ON sentinel_freeze_history(ip);

-- Projected Helix authorization requests (manual approval by Nathan)
CREATE TABLE IF NOT EXISTS helix_authorization (
    id              SERIAL PRIMARY KEY,
    approval_code   VARCHAR(10) NOT NULL UNIQUE,
    status          VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    attacker_ip     VARCHAR(45) NOT NULL,
    sentinel_score  INTEGER DEFAULT 0,
    freeze_history_id INTEGER REFERENCES sentinel_freeze_history(id),
    attacker_profile JSONB DEFAULT '{}',
    proposed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '30 minutes'),
    decided_at      TIMESTAMPTZ,
    decided_by      VARCHAR(20) DEFAULT '',
    notification_sent_email BOOLEAN DEFAULT FALSE,
    notification_sent_sms   BOOLEAN DEFAULT FALSE,
    CONSTRAINT helix_status_check CHECK (status IN ('PENDING', 'APPROVED', 'DENIED', 'EXPIRED'))
);

CREATE INDEX IF NOT EXISTS idx_helix_auth_code ON helix_authorization(approval_code) WHERE status = 'PENDING';
CREATE INDEX IF NOT EXISTS idx_helix_auth_status ON helix_authorization(status, proposed_at DESC);

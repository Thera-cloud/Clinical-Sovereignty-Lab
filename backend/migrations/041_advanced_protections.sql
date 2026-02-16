-- Migration 041: Advanced Protections (Hive Defense v4.0)
-- Infiltrator Trap (Sentinel Mode), Family Data Guardian, minor data access log

-- Sentinel records (30-day post-approval surveillance)
CREATE TABLE IF NOT EXISTS sentinel_records (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             TEXT NOT NULL,
    trigger_reason      TEXT NOT NULL,
    sensitivity_multiplier REAL NOT NULL DEFAULT 1.5,
    mirrors_mode        TEXT DEFAULT 'passive',
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ends_at             TIMESTAMPTZ NOT NULL,
    cross_device_inherit BOOLEAN DEFAULT TRUE,
    resolved            BOOLEAN DEFAULT FALSE,
    resolved_at         TIMESTAMPTZ,
    resolved_by         TEXT
);
CREATE INDEX IF NOT EXISTS idx_sentinel_records_user ON sentinel_records (user_id, ends_at);

-- Minor data access audit log
CREATE TABLE IF NOT EXISTS minor_data_access_log (
    id              BIGSERIAL PRIMARY KEY,
    minor_id        TEXT NOT NULL,
    accessor_id     TEXT NOT NULL,
    accessor_role   TEXT NOT NULL,  -- guardian, coach, admin
    access_type     TEXT NOT NULL,  -- read, write, export
    data_category   TEXT,           -- session, biometrics, notes, family
    guardian_id     TEXT,           -- legal guardian who authorized
    authorized      BOOLEAN NOT NULL,
    reason          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_minor_access_minor ON minor_data_access_log (minor_id, created_at);
CREATE INDEX IF NOT EXISTS idx_minor_access_accessor ON minor_data_access_log (accessor_id);

-- Custody dispute freezes
CREATE TABLE IF NOT EXISTS custody_dispute_records (
    id              BIGSERIAL PRIMARY KEY,
    family_id       TEXT NOT NULL,
    filed_by        TEXT,
    status          TEXT NOT NULL DEFAULT 'active',  -- active, resolved, expired
    data_frozen_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    legal_docs_ref  TEXT,
    resolved_at     TIMESTAMPTZ,
    resolved_by     TEXT,
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_custody_disputes_family ON custody_dispute_records (family_id, status);

-- Encrypted W-9 vault for coaches
CREATE TABLE IF NOT EXISTS coach_w9_vault (
    id              BIGSERIAL PRIMARY KEY,
    coach_id        TEXT UNIQUE NOT NULL,
    encrypted_data  BYTEA NOT NULL,       -- Fernet-encrypted W-9 JSON
    encryption_key_id TEXT NOT NULL,       -- Reference to which key was used
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    verified        BOOLEAN DEFAULT FALSE,
    verified_at     TIMESTAMPTZ,
    verified_by     TEXT
);
CREATE INDEX IF NOT EXISTS idx_w9_vault_coach ON coach_w9_vault (coach_id);

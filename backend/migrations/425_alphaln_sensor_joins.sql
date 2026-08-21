-- Migration 425: AlphaLN Slice 7 — Sensor join schema (Loop D skeleton)
--
-- SCHEMA ONLY. No ingest wiring. No synthetic/fake data. This exists so
-- Slice 7 has a landing zone for real HRV/EDA/sleep samples that a future
-- device integration can push. Until that integration is wired AND a user
-- explicitly consents, this table stays empty.
--
-- Feature flag: ENABLE_ALPHALN_SENSOR_JOIN (default false).
--
-- Consent invariant: rows in this table MUST correspond to a user with
-- `biometrics_disabled=false` and an active `biometrics_consent_at`. Enforced
-- at the ingest hook (not by trigger — we prefer explicit application logic
-- so we can log every insert).

CREATE TABLE IF NOT EXISTS alphaln_sensor_joins (
    id                 BIGSERIAL PRIMARY KEY,
    user_pseudonym     TEXT NOT NULL,          -- HMAC-tokenized; never raw user_id
    device_class       TEXT NOT NULL,          -- 'hrv' | 'eda' | 'sleep' | 'other'
    device_hash        TEXT,                   -- opaque device id (hashed)
    captured_at        TIMESTAMPTZ NOT NULL,
    sample_json        JSONB NOT NULL DEFAULT '{}'::jsonb,
    consent_receipt_id TEXT,                   -- reference to consent audit log
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alphaln_sensor_joins_user
    ON alphaln_sensor_joins(user_pseudonym, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_alphaln_sensor_joins_class
    ON alphaln_sensor_joins(device_class, captured_at DESC);

COMMENT ON TABLE alphaln_sensor_joins IS
    'AlphaLN Slice 7 sensor landing zone. Schema only; no ingest, no synthetic data.';

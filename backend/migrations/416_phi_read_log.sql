-- Migration 416: PHI read log (Slice 6a of Bee HIV+ privacy plan)
--
-- HIPAA §164.528 requires an accounting of disclosures. This table is the
-- append-only audit trail for every read of Protected Health Information
-- (sensitive clinical profile, clinical notes, biometric data, etc.).
--
-- Design rules:
--   1. Append-only. No UPDATE, no DELETE. If a row is wrong, insert a
--      correction row referencing the original via correction_of_id.
--   2. Retained ≥6 years per HIPAA. Excluded from db_maintenance_agent
--      cleanup (add table name to IMMUTABLE_TABLES when that guard exists).
--   3. Actor and subject are captured as usernames (stable identifiers)
--      alongside the UUID when available. This survives username changes
--      via the UUID and survives UUID drift via the username snapshot.
--   4. `fields` is a JSONB array of field-name strings the endpoint
--      returned (e.g. ["trauma_history","medications"]). Empty array is
--      valid ("resource accessed, no PHI fields returned").
--   5. `request_id` links back to the app request log for cross-reference.
--
-- Flag off = no rows written. Empty table has zero runtime cost.

CREATE TABLE IF NOT EXISTS phi_read_log (
    id               BIGSERIAL PRIMARY KEY,
    occurred_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Actor (who read)
    actor_user_id    UUID,
    actor_username   TEXT NOT NULL,
    actor_role       TEXT NOT NULL,               -- 'ADMIN' | 'COACH' | 'CLIENT' | 'SYSTEM'

    -- Subject (whose PHI was read)
    subject_user_id  UUID,
    subject_username TEXT,

    -- What was read
    resource         TEXT NOT NULL,               -- 'sensitive_profile' | 'clinical_notes' | ...
    endpoint         TEXT NOT NULL,               -- request path (e.g. '/api/coach/client/detail/alice')
    method           TEXT NOT NULL DEFAULT 'GET',
    fields           JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Context
    request_id       TEXT,
    ip_address       INET,
    user_agent       TEXT,
    mfa_verified     BOOLEAN NOT NULL DEFAULT FALSE,
    program_id       TEXT,                        -- cohort tag if applicable

    -- Corrections (append-only, so we reference the row this replaces)
    correction_of_id BIGINT REFERENCES phi_read_log(id),
    correction_note  TEXT
);

CREATE INDEX IF NOT EXISTS idx_phi_read_actor ON phi_read_log(actor_username, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_phi_read_subject ON phi_read_log(subject_username, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_phi_read_resource ON phi_read_log(resource, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_phi_read_occurred ON phi_read_log(occurred_at DESC);

COMMENT ON TABLE phi_read_log IS
    'HIPAA §164.528 accounting of disclosures. Append-only. Retain ≥6 years.';

-- Enforce append-only at DB layer: block UPDATE and DELETE.
-- (Rules make this a hard boundary even if application code drifts.)
CREATE OR REPLACE FUNCTION phi_read_log_no_mutate() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'phi_read_log is append-only (op=%)', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_phi_read_log_no_update ON phi_read_log;
CREATE TRIGGER trg_phi_read_log_no_update
    BEFORE UPDATE ON phi_read_log
    FOR EACH ROW EXECUTE FUNCTION phi_read_log_no_mutate();

DROP TRIGGER IF EXISTS trg_phi_read_log_no_delete ON phi_read_log;
CREATE TRIGGER trg_phi_read_log_no_delete
    BEFORE DELETE ON phi_read_log
    FOR EACH ROW EXECUTE FUNCTION phi_read_log_no_mutate();

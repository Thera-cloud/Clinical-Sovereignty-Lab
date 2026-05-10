-- =============================================================================
-- Migration 213: Sensitive Clinical Bridge v1.3 — Phase 6 audit gap closures
--
-- Resolves four sensitive_bridge_auditor checks that were failing because
-- the underlying Postgres objects had not yet landed:
--
--   1. sensitive_log_immutable_enforced
--      → BEFORE UPDATE / BEFORE DELETE triggers on sensitive_bridge_log
--        that raise EXCEPTION (clinician-authored disclosures are append-only,
--        7yr retention per migration 202).
--
--   2. sensitive_log_jurisdiction_trigger_present
--      → BEFORE INSERT trigger that stamps retained_until based on a
--        per-jurisdiction policy lookup (default 7y; Gap L extension point).
--
--   3. safe_silence_state_view_present
--      → safe_silence_state_v view summarizing currently-active safe silence
--        states (consumed by clinician dashboards + auditor cadence check).
--
--   4. safe_silence_expiry_warning_cadence_observed
--      → safe_silence_mode_state table. Without it, _check_safe_silence_*
--        helpers cannot evaluate the day-25 warning / day-30 auto-revert
--        cadence required by Plan v1.3 Phase 5 Note 1.
--
-- All operations are additive (CREATE … IF NOT EXISTS, CREATE OR REPLACE).
-- Re-runnable: dropping and recreating triggers is idempotent.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. Immutability triggers on sensitive_bridge_log
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION sensitive_bridge_log_block_update()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        'sensitive_bridge_log is append-only (7yr retention contract); '
        'UPDATE blocked by sensitive_bridge_log_block_update trigger';
END;
$$;

CREATE OR REPLACE FUNCTION sensitive_bridge_log_block_delete()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    -- Allow deletion only when retention window has expired (retained_until < NOW()).
    -- This matches HIPAA 45 CFR 164.530(j) minimum-retention semantics: rows
    -- past retention are eligible for purge by a maintenance job, but live
    -- rows cannot be silently removed.
    IF OLD.retained_until > NOW() THEN
        RAISE EXCEPTION
            'sensitive_bridge_log row %, retained_until=%, is within '
            '7yr retention window; DELETE blocked',
            OLD.id, OLD.retained_until;
    END IF;
    RETURN OLD;
END;
$$;

DROP TRIGGER IF EXISTS trg_sensitive_bridge_log_no_update ON sensitive_bridge_log;
CREATE TRIGGER trg_sensitive_bridge_log_no_update
    BEFORE UPDATE ON sensitive_bridge_log
    FOR EACH ROW EXECUTE FUNCTION sensitive_bridge_log_block_update();

DROP TRIGGER IF EXISTS trg_sensitive_bridge_log_no_delete ON sensitive_bridge_log;
CREATE TRIGGER trg_sensitive_bridge_log_no_delete
    BEFORE DELETE ON sensitive_bridge_log
    FOR EACH ROW EXECUTE FUNCTION sensitive_bridge_log_block_delete();


-- ---------------------------------------------------------------------------
-- 2. Per-jurisdiction retention trigger (Gap L extension point)
--
-- Default keeps the migration-202 default of 7 years; per-jurisdiction
-- policy rows can be added later without touching the trigger.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sensitive_bridge_jurisdiction_policy (
    jurisdiction         TEXT PRIMARY KEY,
    retention_interval   INTERVAL NOT NULL DEFAULT INTERVAL '7 years',
    notes                TEXT,
    updated_at           TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION sensitive_bridge_log_jurisdiction_retention()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    juris_key   TEXT;
    juris_int   INTERVAL;
BEGIN
    -- payload_json may carry a 'jurisdiction' key (Gap L/jurisdiction-compliance
    -- detector). Fall back to the migration-202 default when absent.
    juris_key := NEW.payload_json ->> 'jurisdiction';
    IF juris_key IS NULL OR juris_key = '' THEN
        RETURN NEW;
    END IF;

    SELECT retention_interval INTO juris_int
    FROM sensitive_bridge_jurisdiction_policy
    WHERE jurisdiction = juris_key;

    IF juris_int IS NOT NULL THEN
        NEW.retained_until := COALESCE(NEW.occurred_at, NOW()) + juris_int;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_sensitive_bridge_log_jurisdiction
    ON sensitive_bridge_log;
CREATE TRIGGER trg_sensitive_bridge_log_jurisdiction
    BEFORE INSERT ON sensitive_bridge_log
    FOR EACH ROW EXECUTE FUNCTION sensitive_bridge_log_jurisdiction_retention();


-- ---------------------------------------------------------------------------
-- 3. safe_silence_mode_state table
--
-- Tracks per-user "safe silence" mode windows. Required by Plan v1.3 Phase 5
-- Note 1 day-25 warning / day-30 auto-revert cadence + the auditor's
-- safe_silence_expiry_warning_cadence_observed check.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS safe_silence_mode_state (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             TEXT NOT NULL,
    active              BOOLEAN NOT NULL DEFAULT TRUE,
    activated_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    expires_at          TIMESTAMP WITH TIME ZONE NOT NULL
                          DEFAULT (NOW() + INTERVAL '30 days'),
    last_warning_at     TIMESTAMP WITH TIME ZONE,
    reverted_at         TIMESTAMP WITH TIME ZONE,
    reason              TEXT,
    created_by          TEXT NOT NULL DEFAULT 'sensitive_clinical_bridge'
);

CREATE INDEX IF NOT EXISTS idx_safe_silence_mode_state_user_active
    ON safe_silence_mode_state(user_id, active);
CREATE INDEX IF NOT EXISTS idx_safe_silence_mode_state_active_expiry
    ON safe_silence_mode_state(active, expires_at)
    WHERE active = TRUE;


-- ---------------------------------------------------------------------------
-- 4. safe_silence_state_v view (clinician dashboard + auditor)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW safe_silence_state_v AS
SELECT
    s.id,
    s.user_id,
    s.active,
    s.activated_at,
    s.expires_at,
    s.last_warning_at,
    s.reverted_at,
    s.reason,
    s.created_by,
    GREATEST(0, EXTRACT(DAY FROM (s.expires_at - NOW()))::INT) AS days_remaining,
    CASE
        WHEN s.active = FALSE                     THEN 'inactive'
        WHEN s.expires_at <= NOW()                THEN 'expired_pending_revert'
        WHEN s.expires_at <= NOW() + INTERVAL '5 days' THEN 'warning_window'
        ELSE 'active'
    END AS lifecycle_state
FROM safe_silence_mode_state s;

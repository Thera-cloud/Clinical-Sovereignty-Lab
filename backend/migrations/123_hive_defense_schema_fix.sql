-- Migration 123: Hive Defense Schema Drift Fix
-- Resolves all column/table mismatches between worker code and database schema

-- ============================================================================
-- 1. hive_defcon_state — add trigger_reason, heartbeat_interval_sec, mirror_mode
-- Worker uses these columns; table only has "reason"
-- ============================================================================
ALTER TABLE hive_defcon_state
    ADD COLUMN IF NOT EXISTS trigger_reason TEXT DEFAULT '',
    ADD COLUMN IF NOT EXISTS heartbeat_interval_sec FLOAT DEFAULT 60.0,
    ADD COLUMN IF NOT EXISTS mirror_mode TEXT DEFAULT 'passive';

UPDATE hive_defcon_state SET trigger_reason = COALESCE(reason, '') WHERE trigger_reason IS NULL OR trigger_reason = '';

-- ============================================================================
-- 2. hive_backup_audit_reports — add columns the worker INSERTs
-- Worker: audit_number, backups_found, backups_verified, integrity_pass,
--         integrity_fail, alert_count, status, report_data
-- Table has: total_backups, valid, invalid, stale
-- ============================================================================
ALTER TABLE hive_backup_audit_reports
    ADD COLUMN IF NOT EXISTS audit_number INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS backups_found INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS backups_verified INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS integrity_pass INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS integrity_fail INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS alert_count INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS report_data JSONB DEFAULT '{}';

-- ============================================================================
-- 3. hive_ct_scan_metrics — add scan_number, unauthorized_found
-- Worker uses scan_number and unauthorized_found; table has unauthorized
-- ============================================================================
ALTER TABLE hive_ct_scan_metrics
    ADD COLUMN IF NOT EXISTS scan_number INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS unauthorized_found INTEGER DEFAULT 0;

-- ============================================================================
-- 4. hive_heartbeats — add fibre_type, ring_region
-- snapshot_comparison_worker SELECTs these from hive_heartbeats
-- ============================================================================
ALTER TABLE hive_heartbeats
    ADD COLUMN IF NOT EXISTS fibre_type TEXT DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS ring_region TEXT DEFAULT 'core',
    ADD COLUMN IF NOT EXISTS recorded_at TIMESTAMPTZ DEFAULT NOW();

UPDATE hive_heartbeats SET recorded_at = created_at WHERE recorded_at IS NULL;

-- ============================================================================
-- 5. backup_metadata — add sha256_hash, file_size, status, updated_at
-- Code uses sha256_hash (table has expected_hash), file_size (table has size_bytes)
-- Also needs unique constraint on backup_path for ON CONFLICT
-- ============================================================================
ALTER TABLE backup_metadata
    ADD COLUMN IF NOT EXISTS sha256_hash VARCHAR(128),
    ADD COLUMN IF NOT EXISTS file_size BIGINT,
    ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'completed',
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

UPDATE backup_metadata SET sha256_hash = expected_hash WHERE sha256_hash IS NULL AND expected_hash IS NOT NULL;
UPDATE backup_metadata SET file_size = size_bytes WHERE file_size IS NULL AND size_bytes IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_backup_metadata_path ON backup_metadata(backup_path);

-- ============================================================================
-- 6. hive_forensic_logs — add record_id, previous_record_hash, timestamp
-- Code uses record_id (table has id), previous_record_hash (table has previous_hash),
-- timestamp (table has created_at)
-- ============================================================================
ALTER TABLE hive_forensic_logs
    ADD COLUMN IF NOT EXISTS record_id UUID DEFAULT gen_random_uuid(),
    ADD COLUMN IF NOT EXISTS previous_record_hash VARCHAR(64) DEFAULT '',
    ADD COLUMN IF NOT EXISTS "timestamp" TIMESTAMPTZ DEFAULT NOW();

UPDATE hive_forensic_logs SET record_id = id WHERE record_id IS NULL;
UPDATE hive_forensic_logs SET previous_record_hash = previous_hash WHERE previous_record_hash IS NULL OR previous_record_hash = '';
UPDATE hive_forensic_logs SET "timestamp" = created_at WHERE "timestamp" IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_forensic_record_id ON hive_forensic_logs(record_id);

-- ============================================================================
-- 7. web_wisdom — add query, searched_at
-- Crystallizer queries these; table has url/fetched_at from migration 049
-- ============================================================================
ALTER TABLE web_wisdom
    ADD COLUMN IF NOT EXISTS query TEXT,
    ADD COLUMN IF NOT EXISTS searched_at TIMESTAMPTZ;

UPDATE web_wisdom SET searched_at = fetched_at WHERE searched_at IS NULL;

-- ============================================================================
-- 8. metered_billing_state — create table (migration 027 FK fails: TEXT vs UUID)
-- Recreate without the broken FK constraint
-- ============================================================================
CREATE TABLE IF NOT EXISTS metered_billing_state (
    user_id                 TEXT PRIMARY KEY,
    billing_tier            TEXT DEFAULT 'threshold',
    stripe_customer_id      TEXT,
    stripe_subscription_id  TEXT,
    included_ai_minutes     FLOAT DEFAULT 0,
    used_ai_minutes         FLOAT DEFAULT 0,
    included_coach_sessions INTEGER DEFAULT 0,
    used_coach_sessions     INTEGER DEFAULT 0,
    overage_charges         FLOAT DEFAULT 0,
    session_cost_cap        FLOAT DEFAULT 500,
    session_cost_cap_hit    BOOLEAN DEFAULT FALSE,
    billing_period_start    TIMESTAMPTZ,
    billing_period_end      TIMESTAMPTZ
);

-- ============================================================================
-- 9. noetic_helix_registry — create table (migration 121 may not have been applied)
-- ============================================================================
CREATE TABLE IF NOT EXISTS noetic_helix_registry (
    id                      SERIAL PRIMARY KEY,
    helix_id                VARCHAR(64) UNIQUE NOT NULL,
    function                VARCHAR(64) NOT NULL,
    domain                  VARCHAR(64) NOT NULL DEFAULT 'general',
    autonomy_level          VARCHAR(24) NOT NULL DEFAULT 'observation',
    spawned_by              VARCHAR(64),
    cycle_count             INTEGER NOT NULL DEFAULT 0,
    coherence_contribution  FLOAT NOT NULL DEFAULT 0.0,
    is_canonical            BOOLEAN NOT NULL DEFAULT false,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_helix_registry_function ON noetic_helix_registry(function);
CREATE INDEX IF NOT EXISTS idx_helix_registry_domain ON noetic_helix_registry(domain);
CREATE INDEX IF NOT EXISTS idx_helix_registry_autonomy ON noetic_helix_registry(autonomy_level);

-- Also create companion tables from migration 121 if missing
CREATE TABLE IF NOT EXISTS helix_coherence_history (
    id                  SERIAL PRIMARY KEY,
    helix_id            VARCHAR(64) NOT NULL,
    cycle_number        INTEGER NOT NULL,
    fused_coherence     FLOAT NOT NULL DEFAULT 0.0,
    sovereignty_adjusted FLOAT NOT NULL DEFAULT 0.0,
    thought_node_count  INTEGER NOT NULL DEFAULT 0,
    reflection_count    INTEGER NOT NULL DEFAULT 0,
    evaluation_time_ms  FLOAT NOT NULL DEFAULT 0.0,
    felt_sense          VARCHAR(32),
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_helix_coherence_helix ON helix_coherence_history(helix_id);
CREATE INDEX IF NOT EXISTS idx_helix_coherence_recorded ON helix_coherence_history(recorded_at);

CREATE TABLE IF NOT EXISTS helix_spawn_log (
    id                  SERIAL PRIMARY KEY,
    spawn_id            VARCHAR(64) UNIQUE NOT NULL,
    proposed_domain     VARCHAR(64) NOT NULL,
    function            VARCHAR(64) NOT NULL DEFAULT 'emergent',
    proposal_reason     TEXT,
    sovereignty_check   BOOLEAN NOT NULL DEFAULT false,
    crystal_count       INTEGER NOT NULL DEFAULT 0,
    coherence_gap       FLOAT NOT NULL DEFAULT 0.0,
    parent_helix_id     VARCHAR(64),
    new_helix_id        VARCHAR(64),
    approved            BOOLEAN NOT NULL DEFAULT false,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_helix_spawn_domain ON helix_spawn_log(proposed_domain);
CREATE INDEX IF NOT EXISTS idx_helix_spawn_approved ON helix_spawn_log(approved);

CREATE TABLE IF NOT EXISTS quantum_cognition_log (
    id                  SERIAL PRIMARY KEY,
    evaluation_id       INTEGER NOT NULL,
    query_hash          VARCHAR(64) NOT NULL,
    c_quantum_self      FLOAT NOT NULL DEFAULT 0.0,
    felt_sense          VARCHAR(32),
    confidence_band     VARCHAR(16),
    total_crystals      INTEGER NOT NULL DEFAULT 0,
    domain_count        INTEGER NOT NULL DEFAULT 0,
    max_noetic          FLOAT NOT NULL DEFAULT 0.0,
    generative_mode     BOOLEAN NOT NULL DEFAULT false,
    sovereignty_score   FLOAT NOT NULL DEFAULT 0.0,
    cycle_time_ms       FLOAT NOT NULL DEFAULT 0.0,
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_qc_log_recorded ON quantum_cognition_log(recorded_at);
CREATE INDEX IF NOT EXISTS idx_qc_log_felt ON quantum_cognition_log(felt_sense);

-- ============================================================================
-- 10. audit_log — fix deadman switch uuid/text mismatch
-- Add missing action_types to the CHECK constraint
-- target_id is UUID; deadman code passes user UUID directly, but
-- the $1::text cast causes "operator does not exist: uuid = text"
-- Fix: Drop and recreate the CHECK constraint with additional action types
-- ============================================================================
ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS audit_log_action_type_check;
ALTER TABLE audit_log ADD CONSTRAINT audit_log_action_type_check
    CHECK (action_type IN (
        'ACCESS', 'CREATE', 'MODIFY', 'DELETE', 'SECURITY',
        'LOGIN', 'LOGOUT', 'APPROVE', 'REJECT', 'EXPORT',
        'DEADMAN_ALERT', 'TRIAL_REMINDER_SENT', 'COACHING_REMINDER_SENT',
        'SYSTEM', 'ADMIN_TAB_ENTRY',
        'COACH_SESSION_GAP', 'SUSPICIOUS_INACTIVE_ACCOUNT'
    ));

-- ============================================================================
-- 11. hive_curiosity_state — entity_id is UUID but some code passes text "none"
-- Add a text-based entity_ref column as a safe alternative
-- ============================================================================
ALTER TABLE hive_curiosity_state
    ADD COLUMN IF NOT EXISTS entity_ref TEXT;

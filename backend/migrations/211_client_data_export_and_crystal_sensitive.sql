-- ============================================================================
-- Migration 211 — Client data export (Gap N) + crystal sensitive seeding columns
-- ============================================================================
--
-- Phase 5 Note 1 (Gap N — HIPAA 45 CFR 164.524 Right of Access) and
-- Phase 5 Note 2 (sensitive crystal sub-domain ingestion) land together
-- because both surfaces are clinical-safety-critical and both need the
-- same self-healing CHECK extension on `sensitive_bridge_log.event_type`.
--
-- ───────────────────────────────────────────────────────────────────────────
-- WHAT THIS MIGRATION DOES
-- ───────────────────────────────────────────────────────────────────────────
--
-- 1) Creates `client_data_export_requests` — the durable record per export
--    request. The row owns the lifecycle:
--      pending → ready → downloaded | expired | failed
--    Three Note 1 invariants live here, not in code:
--      (a) `expires_at` is a TIMESTAMPTZ checked against NOW() on every
--          download attempt (real-clock 7-day window, not session-clock).
--      (b) `download_count` + `max_downloads` enforce single-download via
--          the DB, not via signed-URL secrecy alone (signed URLs can be
--          shared and re-fetched before expiry; the count column makes
--          re-download fail at the row level).
--      (c) `signed_url_token` is opaque and indexed UNIQUE; the router
--          atomically updates `download_count + 1 WHERE download_count <
--          max_downloads AND expires_at > NOW()` — the row's own UPDATE
--          returning rowcount is the gate.
--
-- 2) Adds two columns to `nate_intelligence_crystals`:
--      * `crystal_status` TEXT DEFAULT 'production' CHECK in {'production',
--        'awaiting_clinician_authoring', 'rejected_by_clinician'}.
--        Existing rows default to 'production' (backward compat). New
--        sensitive-domain seed crystals are inserted with status
--        'awaiting_clinician_authoring' so they are NEVER recallable in
--        production until a clinician flips the row to 'production'.
--      * `requires_embodiment_phase` BOOLEAN. NULL allowed for non-sensitive
--        domains (backward compat). MUST be set NON-NULL for crystals in
--        any of the 5 sensitive domains; the auditor enforces this via
--        the folded `sensitive_crystals_embodiment_phase_tagged` check.
--
-- 3) Extends `sensitive_bridge_log.event_type` CHECK constraint to include
--    the new event types written by the Gap N router and the seed-ingestion
--    code path. Self-healing pattern (drop+recreate) per migration 210.
--
-- 4) Adds 1 app_settings row (`data_export_signed_url_ttl_days`) so the
--    Phase 6 auditor can verify the canonical TTL without reading code.
--
-- ───────────────────────────────────────────────────────────────────────────
-- HIPAA REDACTION CONTRACT (Plan v1.3 Note 1)
-- ───────────────────────────────────────────────────────────────────────────
--
-- The router enforces three redaction layers; this migration ENABLES them
-- but does not implement them:
--
--   (a) SQL-LAYER FILTER on access_classification:
--       The router's bundle-generation SELECT explicitly excludes rows
--       whose access_classification is in ('clinician_only',
--       'admin_only_redacted'). This means clinician-clinician
--       communication and validator administrative entries NEVER enter
--       the export process. Python-layer filtering is not used.
--
--   (b) PII PATTERN REUSE:
--       Notes go through `_screen_notes_for_pii` from
--       `trigger_date_registry.py`. Same single-source-of-PII-patterns
--       discipline applied in `coach_override_protocol.build_handoff_payload`.
--       Forking would create silent divergence on pattern updates.
--
--   (c) SINGLE-DOWNLOAD ENFORCEMENT VIA DB:
--       Atomic UPDATE on this table; signed URL is the audience-restricted
--       handle but the count is the lock.
--
-- ============================================================================

BEGIN;

-- ────────────────────────────────────────────────────────────────────────────
-- 1. Extend sensitive_bridge_log.event_type CHECK (self-healing)
-- ────────────────────────────────────────────────────────────────────────────
-- Adds 5 new event types:
--   * data_export_requested            — export request created
--   * data_export_downloaded           — bundle delivered (single-shot)
--   * data_export_expired              — past expires_at without download
--   * crystal_seed_ingested            — sensitive seed crystal stored
--   * crystal_seed_validator_block     — NateResponseValidator rejected seed
--   * crystal_seed_embodiment_block    — sensitive seed missing required tag
--
-- We re-emit the FULL union of allowed event types (210's set + 6 new).
-- This is necessary because PG CHECK lists can't be additively extended.
-- Idempotent: if the constraint already includes the new types, the DROP
-- is a no-op and the ADD re-establishes the same union.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'sensitive_bridge_log'
    ) THEN
        ALTER TABLE sensitive_bridge_log
            DROP CONSTRAINT IF EXISTS sensitive_bridge_log_event_type_check;
        ALTER TABLE sensitive_bridge_log
            ADD CONSTRAINT sensitive_bridge_log_event_type_check
            CHECK (event_type IN (
                -- 33 events from migration 202 (preserved exactly)
                'disclosure_evaluated',
                'introjection_detected',
                'codeword_triggered',
                'codeword_triggered_with_mandatory_reporting_path',
                'arousal_cap_triggered',
                'thalamic_gate_blocked',
                'trigger_date_active',
                'embodiment_phase_filter_applied',
                'reengagement_pattern_detected',
                'polyvictim_load_applied',
                'legal_event_proximity_detected',
                'dual_diagnosis_register_applied',
                'safe_silence_mode_state_change',
                'safe_silence_mode_expiry_warning',
                'safe_silence_mode_auto_reverted',
                'sensitive_profile_mutation',
                'validator_lexicon_filter_applied',
                'validator_minor_protection_filter',
                'validator_parenting_pathologization_filter',
                'reporting_trigger_fired',
                'coach_handoff_emitted',
                'active_trafficking_disclosed',
                'imminent_danger_detected',
                'survivor_recruiter_role_disclosed',
                'jurisdiction_policy_applied',
                'survivor_data_export_requested',
                'minor_survivor_mandatory_reporting_auto_fired',
                'guardian_dual_approval_required',
                'parenting_crisis_alert_fired',
                'rj_companioning_register_applied',
                'cultural_context_register_applied',
                'locale_fallback_applied',
                'gap_feature_auto_disabled',
                -- 5 events from migration 210 (telemetry + 209 backfill)
                'feature_flags_initialized',
                'auto_disable_armed',
                'auto_disable_committed',
                'auto_disable_cancelled',
                'auto_disable_reenabled',
                -- 6 new events in migration 211 (Gap N + crystal seeding)
                'data_export_requested',
                'data_export_downloaded',
                'data_export_expired',
                'crystal_seed_ingested',
                'crystal_seed_validator_block',
                'crystal_seed_embodiment_block'
            ));
    END IF;
END$$;

COMMENT ON COLUMN sensitive_bridge_log.event_type IS
    'Append-only event taxonomy. Extended by migration 211 with 3 '
    'data_export_* events (HIPAA Gap N) and 3 crystal_seed_* events '
    '(sensitive corpus ingestion). Total taxonomy = 44 event types.';


-- ────────────────────────────────────────────────────────────────────────────
-- 2. client_data_export_requests — HIPAA Right of Access bundle requests
-- ────────────────────────────────────────────────────────────────────────────
-- One row per export request. Bundle is stored inline as JSONB so the
-- download endpoint never touches the production tables (audit trail
-- preserved + atomic single-download semantics). Bundle is screened at
-- INSERT time; subsequent reads do not re-screen.
CREATE TABLE IF NOT EXISTS client_data_export_requests (
    request_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 TEXT NOT NULL,
    requested_by            TEXT NOT NULL,
    request_origin          TEXT NOT NULL DEFAULT 'self_service'
        CHECK (request_origin IN ('self_service', 'admin_assist',
                                  'auditor_synthetic')),

    -- Single-download enforcement (Note 1c).
    signed_url_token        TEXT NOT NULL UNIQUE,
    download_count          INTEGER NOT NULL DEFAULT 0
        CHECK (download_count >= 0),
    max_downloads           INTEGER NOT NULL DEFAULT 1
        CHECK (max_downloads >= 1),

    -- Real-clock TTL (Note 1c-ii).
    expires_at              TIMESTAMPTZ NOT NULL,
    last_downloaded_at      TIMESTAMPTZ,
    last_downloader_ip      INET,

    -- Lifecycle.
    status                  TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'ready', 'downloaded',
                          'expired', 'failed')),

    -- Bundle + redaction summary.
    bundle_jsonb            JSONB,                 -- full bundle, inline
    bundle_size_bytes       INTEGER,
    redaction_summary       JSONB NOT NULL DEFAULT '{}'::jsonb,
        -- {"clinician_only_excluded": int, "admin_only_redacted_excluded": int,
        --  "pii_pattern_hits": [{"label": str, "count": int}],
        --  "rows_included": int, "rows_excluded": int}

    -- Auditor synthetic-test hook (Phase 6 fold-in slot).
    is_synthetic            BOOLEAN NOT NULL DEFAULT FALSE,

    failure_reason          TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_client_data_export_requests_user
    ON client_data_export_requests (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_client_data_export_requests_status
    ON client_data_export_requests (status, expires_at);
CREATE INDEX IF NOT EXISTS idx_client_data_export_requests_synthetic
    ON client_data_export_requests (created_at DESC)
    WHERE is_synthetic = TRUE;

COMMENT ON TABLE client_data_export_requests IS
    'HIPAA 45 CFR 164.524 Right of Access — one row per survivor export '
    'request. Bundle is stored inline (bundle_jsonb) so the download path '
    'never touches production tables. Single-download enforced via atomic '
    'UPDATE on download_count; 7-day expiry enforced against NOW() on every '
    'download attempt. Plan v1.3 Note 1 (Gap N).';

COMMENT ON COLUMN client_data_export_requests.signed_url_token IS
    'URL-safe random token (>=32 bytes of entropy). The single audience '
    'restriction; combined with download_count + expires_at it provides '
    'single-shot delivery even if the signed URL is shared post-issue.';

COMMENT ON COLUMN client_data_export_requests.download_count IS
    'Incremented atomically on each successful download. The download '
    'endpoint runs UPDATE ... SET download_count = download_count + 1 '
    'WHERE download_count < max_downloads AND expires_at > NOW() RETURNING; '
    'an empty RETURNING means the request is exhausted or expired (410 Gone).';

COMMENT ON COLUMN client_data_export_requests.is_synthetic IS
    'TRUE for auditor-issued synthetic export requests (single-download '
    'enforcement self-test). Synthetic rows are excluded from user-facing '
    'history endpoints and are auto-pruned after 24h.';

COMMENT ON COLUMN client_data_export_requests.redaction_summary IS
    'Summary of what the SQL-layer access_classification filter excluded '
    'and what _screen_notes_for_pii redacted. Allows the auditor to verify '
    'redaction was actually applied (not just claimed).';

-- Update updated_at on any change.
CREATE OR REPLACE FUNCTION _touch_client_data_export_requests()
    RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_touch_client_data_export_requests
    ON client_data_export_requests;
CREATE TRIGGER trg_touch_client_data_export_requests
    BEFORE UPDATE ON client_data_export_requests
    FOR EACH ROW EXECUTE FUNCTION _touch_client_data_export_requests();


-- ────────────────────────────────────────────────────────────────────────────
-- 3. nate_intelligence_crystals — sensitive seed columns (Note 2)
-- ────────────────────────────────────────────────────────────────────────────
-- crystal_status:
--   * 'production' (default) — recallable; existing crystals are unchanged
--   * 'awaiting_clinician_authoring' — engineer-authored scaffolding;
--     NEVER recalled in production until a clinician reviews and flips
--     the row to 'production' (the gate-to-recallability per Note 2c).
--   * 'rejected_by_clinician' — clinician reviewed and rejected; preserved
--     for audit but never recalled.
ALTER TABLE nate_intelligence_crystals
    ADD COLUMN IF NOT EXISTS crystal_status TEXT
        DEFAULT 'production'
        CHECK (crystal_status IN ('production',
                                  'awaiting_clinician_authoring',
                                  'rejected_by_clinician'));

-- requires_embodiment_phase:
--   * NULL allowed (backward compat for non-sensitive domains).
--   * Mandatory NOT NULL for crystals in any of the 5 sensitive domains
--     (intimacy_clinical, sexual_trauma, trafficking_trauma,
--      embodiment_repair, child_trafficking). The ingestion code-path
--     enforces this; the auditor verifies via the folded check
--     `sensitive_crystals_embodiment_phase_tagged` (zero-row expectation).
--   * The DB does NOT enforce the mandatory-tag rule because legacy crystals
--     pre-date the contract; enforcement is at INSERT time in
--     `bulk_crystal_ingestion.ingest_clinical_seed_crystals()` and at
--     read time in the auditor.
ALTER TABLE nate_intelligence_crystals
    ADD COLUMN IF NOT EXISTS requires_embodiment_phase BOOLEAN;

CREATE INDEX IF NOT EXISTS idx_crystals_status
    ON nate_intelligence_crystals (crystal_status)
    WHERE crystal_status != 'production';

CREATE INDEX IF NOT EXISTS idx_crystals_sensitive_embodiment
    ON nate_intelligence_crystals (domain)
    WHERE requires_embodiment_phase = TRUE;

COMMENT ON COLUMN nate_intelligence_crystals.crystal_status IS
    'Lifecycle gate. ''production'' = recallable. '
    '''awaiting_clinician_authoring'' = engineer scaffolding pending '
    'clinician review (NEVER surfaces in recall). ''rejected_by_clinician'' '
    '= reviewed-and-rejected (preserved for audit). Plan v1.3 Note 2c.';

COMMENT ON COLUMN nate_intelligence_crystals.requires_embodiment_phase IS
    'Plan v1.3 Note 2b: mandatory NOT NULL for the 5 sensitive crystal '
    'domains (intimacy_clinical, sexual_trauma, trafficking_trauma, '
    'embodiment_repair, child_trafficking). When TRUE, the orchestrator '
    'gates recall behind embodiment-phase availability.';


-- ────────────────────────────────────────────────────────────────────────────
-- 4. app_settings — data export TTL canonical config
-- ────────────────────────────────────────────────────────────────────────────
INSERT INTO app_settings (setting_key, setting_value, description, updated_by)
VALUES (
    'data_export_signed_url_ttl_days',
    '7'::jsonb,
    'Real-clock TTL in days for client_data_export_requests.expires_at. '
    'Plan v1.3 Note 1c-ii: signed URL is checked against NOW() on every '
    'download attempt, not against session start. Auditor verifies this '
    'value matches the router default and equals 7.',
    'migration_211'
)
ON CONFLICT (setting_key) DO NOTHING;

INSERT INTO app_settings (setting_key, setting_value, description, updated_by)
VALUES (
    'sensitive_crystal_seed_domains',
    '[
        "intimacy_clinical",
        "sexual_trauma",
        "trafficking_trauma",
        "embodiment_repair",
        "child_trafficking"
    ]'::jsonb,
    'The 5 sensitive crystal domains where requires_embodiment_phase is '
    'mandatory at ingestion (Plan v1.3 Note 2b). Auditor reads this list '
    'when running sensitive_crystals_embodiment_phase_tagged.',
    'migration_211'
)
ON CONFLICT (setting_key) DO NOTHING;


-- ────────────────────────────────────────────────────────────────────────────
-- 5. Audit row — record migration apply
-- ────────────────────────────────────────────────────────────────────────────
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_name = 'sensitive_bridge_log') THEN
        INSERT INTO sensitive_bridge_log (
            user_id, event_type, event_severity,
            payload_json, recorded_by, access_classification, pii_screened_at
        ) VALUES (
            'system',
            'feature_flags_initialized',
            'info',
            jsonb_build_object(
                'migration', '211_client_data_export_and_crystal_sensitive',
                'client_data_export_requests_created', true,
                'crystal_status_column_added', true,
                'requires_embodiment_phase_column_added', true,
                'event_type_check_extended', jsonb_build_array(
                    'data_export_requested',
                    'data_export_downloaded',
                    'data_export_expired',
                    'crystal_seed_ingested',
                    'crystal_seed_validator_block',
                    'crystal_seed_embodiment_block'
                ),
                'note1_redaction_layers_enabled', jsonb_build_array(
                    'sql_layer_access_classification_filter',
                    'pii_screen_helper_reuse',
                    'single_download_enforcement_via_db_count'
                ),
                'note2_crystal_corpus_contracts_enabled', jsonb_build_array(
                    'nate_response_validator_required_at_ingestion',
                    'requires_embodiment_phase_mandatory_for_5_sensitive_domains',
                    'awaiting_clinician_authoring_default_for_seeds',
                    'recall_excludes_awaiting_clinician_authoring'
                )
            ),
            'migration_211',
            'admin_only_redacted',
            NOW()
        );
    END IF;
END$$;

COMMIT;

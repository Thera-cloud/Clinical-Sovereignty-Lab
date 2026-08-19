-- Studio consent is NOT public.consent_records (identity/workspace table).
-- Additive. Revoke accidental studio_runtime grant. QUANTUM-CRYSTAL-ARCH

CREATE TABLE IF NOT EXISTS studio_consent_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    show_id UUID NOT NULL REFERENCES studio_shows (id),
    caller_id UUID REFERENCES show_callers (id),
    consent_kind TEXT NOT NULL,
    granted BOOLEAN NOT NULL DEFAULT FALSE,
    source TEXT NOT NULL DEFAULT 'screener',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT studio_consent_kind_chk CHECK (
        consent_kind IN ('air', 'recording', 'recall', 'sms_opt_in')
    )
);

CREATE INDEX IF NOT EXISTS idx_studio_consent_records_show
    ON studio_consent_records (show_id, created_at DESC);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'studio_runtime') THEN
        IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'consent_records'
        ) THEN
            EXECUTE 'REVOKE ALL ON TABLE consent_records FROM studio_runtime';
        END IF;
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE studio_consent_records TO studio_runtime';
        IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'studio_youtube_connection'
        ) THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE studio_youtube_connection TO studio_runtime';
        END IF;
    END IF;
END $$;

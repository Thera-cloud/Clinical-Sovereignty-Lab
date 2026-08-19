-- S2–S5 additive columns: YouTube OAuth, RTMP key. QUANTUM-CRYSTAL-ARCH

ALTER TABLE studio_shows
    ADD COLUMN IF NOT EXISTS rtmp_url TEXT;

CREATE TABLE IF NOT EXISTS studio_youtube_connection (
    coach_id VARCHAR PRIMARY KEY,
    refresh_ciphertext TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'studio_runtime') THEN
        GRANT SELECT, INSERT, UPDATE ON TABLE studio_youtube_connection TO studio_runtime;
    END IF;
END $$;

-- S2–S5 remaining: dump spans, speaker utterances, YouTube channel cols, CoachN show seed.
-- Additive only. Does not create accounts. QUANTUM-CRYSTAL-ARCH

ALTER TABLE session_legs
    ADD COLUMN IF NOT EXISTS utterances_json JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE studio_episodes
    ADD COLUMN IF NOT EXISTS media_r2_key TEXT,
    ADD COLUMN IF NOT EXISTS youtube_video_id TEXT;

ALTER TABLE studio_youtube_connection
    ADD COLUMN IF NOT EXISTS access_ciphertext TEXT,
    ADD COLUMN IF NOT EXISTS channel_id TEXT,
    ADD COLUMN IF NOT EXISTS channel_name TEXT;

CREATE TABLE IF NOT EXISTS studio_dump_spans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES studio_sessions (id),
    show_id UUID NOT NULL REFERENCES studio_shows (id),
    delay_s INT NOT NULL DEFAULT 45,
    irreversible BOOLEAN NOT NULL DEFAULT TRUE,
    dumped_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_studio_dump_spans_session
    ON studio_dump_spans (session_id, dumped_at DESC);

INSERT INTO studio_shows (coach_id, name, description, vertical)
SELECT
    'COACH_COACHN_ID',
    'CoachN Studio',
    'Educational show with an AI co-host and knowledge companion.',
    'life_coaching'
WHERE NOT EXISTS (
    SELECT 1 FROM studio_shows WHERE coach_id = 'COACH_COACHN_ID'
);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'studio_runtime') THEN
        GRANT SELECT, INSERT, UPDATE ON TABLE studio_dump_spans TO studio_runtime;
        GRANT SELECT, INSERT, UPDATE ON TABLE studio_youtube_connection TO studio_runtime;
        GRANT SELECT, INSERT, UPDATE ON TABLE session_legs TO studio_runtime;
        GRANT SELECT, INSERT, UPDATE ON TABLE studio_episodes TO studio_runtime;
        GRANT SELECT, INSERT, UPDATE ON TABLE studio_shows TO studio_runtime;
    END IF;
END $$;

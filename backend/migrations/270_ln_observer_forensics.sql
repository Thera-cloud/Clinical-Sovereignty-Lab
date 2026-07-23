-- Migration 270: LN-Observer session forensics — A/V temporal alignment
-- Additive only. Pairs audio windows to nearest visual frames.

ALTER TABLE ln_observer_transcripts
    DROP CONSTRAINT IF EXISTS ln_observer_transcripts_source_check;

ALTER TABLE ln_observer_transcripts
    ADD CONSTRAINT ln_observer_transcripts_source_check
    CHECK (source IN (
        'audio_transcript',
        'frame_observation',
        'coach_chat',
        'ln_chat',
        'system',
        'av_bundle',
        'frame_meta'
    ));

ALTER TABLE ln_observer_transcripts
    ADD COLUMN IF NOT EXISTS meta JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS ln_observer_forensic_events (
    id              BIGSERIAL PRIMARY KEY,
    session_id      UUID NOT NULL
                    REFERENCES ln_observer_sessions(session_id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type      TEXT NOT NULL,
    t_start         TIMESTAMPTZ,
    t_end           TIMESTAMPTZ,
    frame_id        TEXT,
    frame_delta_ms  INTEGER,
    audio_text      TEXT,
    seen_text       TEXT,
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_lnobs_forensic_sess
    ON ln_observer_forensic_events (session_id, created_at DESC);

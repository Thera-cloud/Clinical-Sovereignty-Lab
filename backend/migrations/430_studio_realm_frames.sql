-- 430: Rotating Thera-world realms for the STUDIO live room.
-- Each row is one generated backdrop frame behind Little Nate. Frames
-- accumulate as a library; the newest row for a session is what is on air.
-- Additive only.

CREATE TABLE IF NOT EXISTS studio_realm_frames (
    id           BIGSERIAL PRIMARY KEY,
    session_id   UUID,
    slug         TEXT        NOT NULL,
    name         TEXT        NOT NULL,
    blurb        TEXT        NOT NULL DEFAULT '',
    r2_key       TEXT        NOT NULL DEFAULT '',
    byte_size    INTEGER     NOT NULL DEFAULT 0,
    provider     TEXT        NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_studio_realm_frames_session
    ON studio_realm_frames (session_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_studio_realm_frames_slug
    ON studio_realm_frames (slug, created_at DESC);

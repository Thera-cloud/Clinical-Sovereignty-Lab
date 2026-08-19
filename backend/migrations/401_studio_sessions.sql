-- Sovereign Studio S1 — sessions + legs. INV-1 show_mode CHECK. INV-2 guest video CHECK.
-- Additive only. QUANTUM-CRYSTAL-ARCH

CREATE TABLE IF NOT EXISTS studio_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    show_id UUID NOT NULL REFERENCES studio_shows (id),
    show_mode BOOLEAN NOT NULL DEFAULT TRUE,
    state TEXT NOT NULL DEFAULT 'preflight',
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT studio_sessions_show_mode_chk CHECK (show_mode = TRUE),
    CONSTRAINT studio_sessions_state_chk CHECK (state IN ('preflight', 'active', 'ended'))
);

CREATE INDEX IF NOT EXISTS idx_studio_sessions_show
    ON studio_sessions (show_id, created_at DESC);

CREATE TABLE IF NOT EXISTS session_legs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES studio_sessions (id),
    role TEXT NOT NULL,
    label TEXT,
    video_track_key TEXT,
    audio_track_key TEXT,
    state TEXT NOT NULL DEFAULT 'idle',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT session_legs_role_chk CHECK (role IN ('host', 'cohost_ai', 'guest')),
    CONSTRAINT session_legs_guest_audio_only_chk CHECK (
        role <> 'guest' OR video_track_key IS NULL
    )
);

CREATE INDEX IF NOT EXISTS idx_session_legs_session
    ON session_legs (session_id, role);

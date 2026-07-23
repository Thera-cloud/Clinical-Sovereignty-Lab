-- Migration 266: LN-Observer sessions, transcripts, approval gate, activation log
-- Additive only. Clinical-AGI-class Observer surface (Gap 6 + session topology).

CREATE TABLE IF NOT EXISTS ln_observer_approvals (
    coach_id        TEXT PRIMARY KEY,
    coach_name      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'revoked')),
    requested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_by      TEXT,
    decided_at      TIMESTAMPTZ,
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS ln_observer_activation_log (
    id                  BIGSERIAL PRIMARY KEY,
    session_id          UUID NOT NULL,
    coach_id            TEXT NOT NULL,
    coach_name          TEXT NOT NULL,
    activated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    deactivated_at      TIMESTAMPTZ,
    responsibility_ack  BOOLEAN NOT NULL DEFAULT TRUE,
    ack_text_version    TEXT NOT NULL DEFAULT 'v1',
    client_ip           TEXT,
    user_agent          TEXT
);
CREATE INDEX IF NOT EXISTS idx_lnobs_actlog_coach
    ON ln_observer_activation_log (coach_id, activated_at DESC);

CREATE TABLE IF NOT EXISTS ln_observer_sessions (
    session_id      UUID PRIMARY KEY,
    coach_id        TEXT NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at        TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'live'
                    CHECK (status IN ('live', 'ended', 'error', 'reconnecting')),
    frame_count     INTEGER NOT NULL DEFAULT 0,
    audio_seconds   INTEGER NOT NULL DEFAULT 0,
    ln_summary      TEXT,
    context_bundle  TEXT,
    ws_ticket       TEXT,
    disconnected_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_lnobs_sessions_reconnect
    ON ln_observer_sessions (status, disconnected_at)
    WHERE status = 'reconnecting';

CREATE TABLE IF NOT EXISTS ln_observer_transcripts (
    id          BIGSERIAL PRIMARY KEY,
    session_id  UUID NOT NULL REFERENCES ln_observer_sessions(session_id) ON DELETE CASCADE,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    source      TEXT NOT NULL
                CHECK (source IN (
                    'audio_transcript', 'frame_observation',
                    'coach_chat', 'ln_chat', 'system'
                )),
    content     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lnobs_tx_session
    ON ln_observer_transcripts (session_id, ts);

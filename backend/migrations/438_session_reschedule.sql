-- QUANTUM-CRYSTAL-ARCH: coach Schedule reschedule audit (billing + reminder void)
CREATE TABLE IF NOT EXISTS session_reschedule_log (
    id BIGSERIAL PRIMARY KEY,
    old_session_id TEXT NOT NULL,
    new_session_id TEXT NOT NULL,
    coach_id TEXT NOT NULL DEFAULT '',
    client_id TEXT NOT NULL DEFAULT '',
    old_start TIMESTAMPTZ,
    new_start TIMESTAMPTZ,
    rescheduled_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_session_reschedule_old
    ON session_reschedule_log (old_session_id);
CREATE INDEX IF NOT EXISTS idx_session_reschedule_new
    ON session_reschedule_log (new_session_id);
CREATE INDEX IF NOT EXISTS idx_session_reschedule_coach
    ON session_reschedule_log (coach_id, created_at DESC);

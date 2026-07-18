-- Migration 248: High-risk occupational crisis engine
-- QUANTUM-CRYSTAL-ARCH
-- Additive only. population / population_shielded live in profile_data JSONB (no ALTER).

CREATE TABLE IF NOT EXISTS checkin_risk_windows (
    id              BIGSERIAL PRIMARY KEY,
    username        TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
    reason          TEXT NOT NULL CHECK (reason IN (
        'post_p0', 'post_p1', 'trigger_date', 'family_concern', 'critical_incident'
    )),
    cadence_hours   INT NOT NULL DEFAULT 24 CHECK (cadence_hours >= 6 AND cadence_hours <= 72),
    opened_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,
    closed_at       TIMESTAMPTZ,
    close_reason    TEXT,
    opened_by       TEXT NOT NULL DEFAULT 'system',
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_checkin_risk_windows_active
    ON checkin_risk_windows (username, expires_at)
    WHERE closed_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_checkin_risk_windows_reason
    ON checkin_risk_windows (reason, opened_at DESC);

COMMENT ON TABLE checkin_risk_windows IS
  'Time-boxed shortened check-in cadences after P0/P1, trigger dates, or family concern. '
  'Parallel to NateCheckInAgent backoff (which only stretches). Snooze/safe_silence still win.';

CREATE TABLE IF NOT EXISTS family_concern_flags (
    id                BIGSERIAL PRIMARY KEY,
    target_username   TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
    flagger_username  TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
    relationship      TEXT NOT NULL DEFAULT 'family',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata          JSONB NOT NULL DEFAULT '{}'::jsonb
    -- Never store conversation content. Who + when only.
);

CREATE INDEX IF NOT EXISTS idx_family_concern_flags_target
    ON family_concern_flags (target_username, created_at DESC);

COMMENT ON TABLE family_concern_flags IS
  'Family member concern flag — raises check-in attentiveness without leaking message content.';

-- Optional date_type extensions for occupational risk (additive CHECK via new allowed values
-- requires drop/recreate — skip; use 'other' + notes_redacted for deployment/alive-day etc.)

INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES (
    'high_risk_crisis_check_count',
    '{"expected": 8, "description": "High-risk occupational crisis API checks"}'::jsonb
)
ON CONFLICT (parameter_key) DO UPDATE
SET parameter_value = EXCLUDED.parameter_value;

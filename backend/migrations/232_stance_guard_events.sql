-- Stance guard-hit telemetry (QUANTUM-CRYSTAL-ARCH)
-- Append-only flight recorder when post-gen guards mutate Nate's reply.

CREATE TABLE IF NOT EXISTS stance_guard_events (
    id              BIGSERIAL PRIMARY KEY,
    uid             TEXT,
    turn_index      INT,
    session_id      TEXT,
    guard_id        TEXT NOT NULL,
    event_kind      TEXT NOT NULL DEFAULT 'mutation',
    trigger         TEXT,
    chars_before    INT,
    chars_after     INT,
    pct_stripped    REAL,
    fallback_used   BOOLEAN DEFAULT false,
    user_signals    JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stance_guard_events_uid_created
    ON stance_guard_events (uid, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_stance_guard_events_guard_created
    ON stance_guard_events (guard_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_stance_guard_events_kind_created
    ON stance_guard_events (event_kind, created_at DESC);

-- Stance Loop Auditor: 3 → 5 checks (guard table + bait-gap signal)
UPDATE trust_baseline
SET parameter_value = jsonb_set(
    parameter_value,
    '{expected}',
    '5'::jsonb
)
WHERE parameter_key = 'stance_loop_check_count';

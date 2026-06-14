-- Migration 230: Daily Reconnect Ritual (additive)
-- user_id columns store users.username (not hardware_id)

CREATE TABLE IF NOT EXISTS daily_reconnect_session (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_id TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'CONSENT_CHECKPOINT',
    sanctuary_id TEXT,
    total_reconnects INT NOT NULL DEFAULT 0,
    last_reconnect_at TIMESTAMPTZ,
    scheduled_for TIMESTAMPTZ,
    soft_incident_count INT NOT NULL DEFAULT 0,
    soft_turns_in_incident INT NOT NULL DEFAULT 0,
    rolling_escalation JSONB NOT NULL DEFAULT '{}'::jsonb,
    current_prompt_index INT NOT NULL DEFAULT 0,
    turn_order JSONB NOT NULL DEFAULT '[]'::jsonb,
    current_turn_user_id TEXT,
    cooldown_hours INT,
    cooldown_lock_until TIMESTAMPTZ,
    warning_until TIMESTAMPTZ,
    crisis_bypass_at TIMESTAMPTZ,
    enter_fs_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_daily_reconnect_session_family
    ON daily_reconnect_session (family_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_daily_reconnect_session_state
    ON daily_reconnect_session (state) WHERE closed_at IS NULL;

CREATE TABLE IF NOT EXISTS daily_reconnect_participant (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES daily_reconnect_session(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    family_role TEXT,
    consent_ack_at TIMESTAMPTZ,
    cooldown_choice_hours INT,
    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    left_at TIMESTAMPTZ,
    UNIQUE (session_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_daily_reconnect_participant_user
    ON daily_reconnect_participant (user_id, joined_at DESC);

CREATE TABLE IF NOT EXISTS daily_reconnect_turn (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES daily_reconnect_session(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    prompt_index INT NOT NULL,
    prompt_kind TEXT NOT NULL,
    content TEXT NOT NULL,
    temperature REAL,
    temperature_detail JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (session_id, user_id, prompt_index)
);
CREATE INDEX IF NOT EXISTS idx_daily_reconnect_turn_session
    ON daily_reconnect_turn (session_id, created_at);

CREATE TABLE IF NOT EXISTS daily_reconnect_inference (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES daily_reconnect_session(id) ON DELETE CASCADE,
    connection_indicator INT CHECK (connection_indicator BETWEEN 1 AND 10),
    attachment_hypothesis TEXT,
    position TEXT,
    basis_json JSONB DEFAULT '{}'::jsonb,
    framing TEXT NOT NULL DEFAULT 'observed_signal_not_assessment',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_daily_reconnect_inference_session
    ON daily_reconnect_inference (session_id, created_at DESC);

CREATE TABLE IF NOT EXISTS daily_reconnect_event (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES daily_reconnect_session(id) ON DELETE SET NULL,
    family_id TEXT,
    event_type TEXT NOT NULL,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_daily_reconnect_event_session
    ON daily_reconnect_event (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_daily_reconnect_event_type
    ON daily_reconnect_event (event_type, created_at DESC);

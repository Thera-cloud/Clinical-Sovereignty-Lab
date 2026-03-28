-- Sovereign Voice v3.1 + Call Center: metering, outreach, callbacks, coach notifications
-- All user FKs use UUID -> users(id)

CREATE TABLE IF NOT EXISTS voice_call_usage (
    id BIGSERIAL PRIMARY KEY,
    user_uuid UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    year_month TEXT NOT NULL,
    minutes_used NUMERIC(10,2) NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_uuid, year_month)
);

CREATE INDEX IF NOT EXISTS idx_voice_call_usage_user ON voice_call_usage(user_uuid);

CREATE TABLE IF NOT EXISTS user_outreach_preferences (
    user_uuid UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    quiet_hours_start TIME,
    quiet_hours_end TIME,
    last_hold_experience TEXT,
    outreach_opt_in BOOLEAN DEFAULT TRUE,
    preferences JSONB DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS outreach_events (
    id BIGSERIAL PRIMARY KEY,
    user_uuid UUID REFERENCES users(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    payload JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_outreach_events_user ON outreach_events(user_uuid, created_at DESC);

CREATE TABLE IF NOT EXISTS voice_filler_events (
    id BIGSERIAL PRIMARY KEY,
    user_uuid UUID REFERENCES users(id) ON DELETE SET NULL,
    call_sid TEXT,
    filler_profile TEXT,
    filler_hash TEXT,
    played_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS voice_session_biometrics (
    id BIGSERIAL PRIMARY KEY,
    user_uuid UUID REFERENCES users(id) ON DELETE SET NULL,
    call_sid TEXT NOT NULL,
    payload JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS callback_queue (
    id BIGSERIAL PRIMARY KEY,
    user_uuid UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    priority SMALLINT NOT NULL DEFAULT 5,
    reason TEXT,
    tone_template TEXT,
    rissc_profile TEXT,
    promised_by TIMESTAMPTZ,
    scheduled_for TIMESTAMPTZ,
    attempt_count INT DEFAULT 0,
    max_attempts INT DEFAULT 3,
    status TEXT NOT NULL DEFAULT 'pending',
    coach_notified BOOLEAN DEFAULT FALSE,
    call_sid_ref TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_callback_queue_pending ON callback_queue (priority, scheduled_for ASC)
    WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS voice_hold_sessions (
    id BIGSERIAL PRIMARY KEY,
    call_sid TEXT NOT NULL,
    user_uuid UUID REFERENCES users(id) ON DELETE SET NULL,
    experience TEXT,
    queue_position INT,
    enqueued_at TIMESTAMPTZ DEFAULT NOW(),
    status TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS coach_escalation_notifications (
    id BIGSERIAL PRIMARY KEY,
    coach_username TEXT NOT NULL,
    urgency TEXT NOT NULL,
    subject TEXT,
    message TEXT,
    channels JSONB DEFAULT '[]'::jsonb,
    payload JSONB DEFAULT '{}'::jsonb,
    read_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_coach_esc_notif_coach ON coach_escalation_notifications(coach_username, created_at DESC);

-- Speed up E.164 / digit-based phone match (normalize to digits only in queries)
CREATE INDEX IF NOT EXISTS idx_users_phone_digits
ON users ((regexp_replace(COALESCE(profile_data->>'phone', ''), '[^0-9]', '', 'g')))
WHERE profile_data->>'phone' IS NOT NULL AND btrim(profile_data->>'phone') <> '';

-- trust_baseline skyeye_endpoint_count: keep in sync with skyeye_tab_auditor.py TAB_ENDPOINTS
-- (already governed by migration 134 — do not bump here without adding matching auditor routes)

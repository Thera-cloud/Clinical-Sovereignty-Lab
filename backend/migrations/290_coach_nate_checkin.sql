-- Coach-requested Little Nate client check-in (outbound + callback verify).
-- QUANTUM-CRYSTAL-ARCH / SOVEREIGN-VOICE
-- Billing: billed_to=platform while COACH_NATE_CHECKIN_BILLING_ENABLED=false.

CREATE TABLE IF NOT EXISTS coach_nate_checkin_tasks (
    id                  BIGSERIAL PRIMARY KEY,
    coach_username      TEXT NOT NULL,
    client_username     TEXT NOT NULL,
    client_hardware_id  TEXT,
    client_phone_e164   TEXT,
    status              TEXT NOT NULL DEFAULT 'queued',
    outcome             TEXT,
    intent              TEXT NOT NULL DEFAULT 'coach_checkin',
    call_id             UUID,
    outbound_call_sid   TEXT,
    callback_call_sid   TEXT,
    verified            BOOLEAN NOT NULL DEFAULT FALSE,
    verify_method       TEXT,
    voice_match_ok      BOOLEAN,
    last_voice_check_at TIMESTAMPTZ,
    confidential_unlocked BOOLEAN NOT NULL DEFAULT FALSE,
    billable_seconds    INT NOT NULL DEFAULT 0,
    twilio_cost_est_cents INT NOT NULL DEFAULT 0,
    billed_to           TEXT NOT NULL DEFAULT 'platform',
    billing_charged     BOOLEAN NOT NULL DEFAULT FALSE,
    opening_line        TEXT,
    voicemail_left_at   TIMESTAMPTZ,
    answered_at         TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    error_detail        TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_coach_nate_checkin_coach_created
    ON coach_nate_checkin_tasks (coach_username, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_coach_nate_checkin_client_created
    ON coach_nate_checkin_tasks (client_username, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_coach_nate_checkin_status
    ON coach_nate_checkin_tasks (status) WHERE status NOT IN ('completed', 'failed', 'cancelled');
CREATE INDEX IF NOT EXISTS idx_coach_nate_checkin_phone
    ON coach_nate_checkin_tasks (client_phone_e164)
    WHERE client_phone_e164 IS NOT NULL AND client_phone_e164 != '';

CREATE TABLE IF NOT EXISTS coach_nate_checkin_events (
    id          BIGSERIAL PRIMARY KEY,
    task_id     BIGINT NOT NULL REFERENCES coach_nate_checkin_tasks(id) ON DELETE CASCADE,
    event_type  TEXT NOT NULL,
    detail      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_coach_nate_checkin_events_task
    ON coach_nate_checkin_events (task_id, created_at DESC);

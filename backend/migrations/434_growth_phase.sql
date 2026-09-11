-- QUANTUM-CRYSTAL-ARCH: Growth-Phase Architecture (thrive package) — v1
-- Additive only. Canonical identity = users.username (sensitive-bridge rule).
--
-- Persists the heal→thrive phase per client, the audit trail of every phase
-- move (auto-promotion, coach override, working-through / crisis-hold), the
-- four positive-psychology focus areas + anchor-practice cadence, in-house
-- strengths inventory, and the LN entry greeting log. Goals reuse
-- nate_commitments (238); streaks reuse therapeutic_habit_tracking (129);
-- healing-cycle signal reuses cycle_observations/cycle_detections with
-- domain = 'healing' (129); journeys/quests reuse sse_* (174b).

-- ── 1. Phase state ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS client_growth_phase (
    username        TEXT PRIMARY KEY REFERENCES users(username) ON DELETE CASCADE,
    phase           TEXT NOT NULL DEFAULT 'process'
        CHECK (phase IN ('stabilize', 'process', 'consolidate', 'thrive', 'generative')),
    sub_state       TEXT
        CHECK (sub_state IS NULL OR sub_state IN ('working_through', 'crisis_hold')),
    sub_state_until TIMESTAMPTZ,
    phase_since     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    healing_score   NUMERIC(5,4),
    score_streak    INTEGER NOT NULL DEFAULT 0,
    coach_override  BOOLEAN NOT NULL DEFAULT FALSE,
    set_by          TEXT NOT NULL DEFAULT 'auto',
    last_evaluated  TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS client_growth_phase_history (
    id              BIGSERIAL PRIMARY KEY,
    username        TEXT NOT NULL,
    from_phase      TEXT,
    to_phase        TEXT NOT NULL,
    from_sub_state  TEXT,
    to_sub_state    TEXT,
    reason          TEXT NOT NULL,
    healing_score   NUMERIC(5,4),
    evidence        JSONB NOT NULL DEFAULT '{}'::jsonb,
    set_by          TEXT NOT NULL DEFAULT 'auto',
    coach_notified  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_growth_phase_history_user
    ON client_growth_phase_history (username, created_at DESC);

-- ── 2. Focus areas + anchor-practice cadence ─────────────────────────────
CREATE TABLE IF NOT EXISTS client_focus_areas (
    username            TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
    focus_area          TEXT NOT NULL
        CHECK (focus_area IN ('daily_happiness', 'future_direction',
                              'self_compassion_confidence', 'handling_stress')),
    practice_key        TEXT NOT NULL,
    cadence             TEXT NOT NULL DEFAULT 'daily'
        CHECK (cadence IN ('daily', 'weekdays', '3x_week', 'weekly', 'once')),
    time_of_day         TEXT NOT NULL DEFAULT 'evening'
        CHECK (time_of_day IN ('morning', 'midday', 'evening', 'late_night', 'any')),
    active              BOOLEAN NOT NULL DEFAULT TRUE,
    source              TEXT NOT NULL DEFAULT 'ln'
        CHECK (source IN ('ln', 'client', 'coach')),
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_completed_at   TIMESTAMPTZ,
    next_due_at         TIMESTAMPTZ,
    streak              INTEGER NOT NULL DEFAULT 0,
    longest_streak      INTEGER NOT NULL DEFAULT 0,
    total_completions   INTEGER NOT NULL DEFAULT 0,
    total_reminders     INTEGER NOT NULL DEFAULT 0,
    last_reminder_at    TIMESTAMPTZ,
    notes               TEXT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (username, practice_key)
);
CREATE INDEX IF NOT EXISTS idx_client_focus_areas_due
    ON client_focus_areas (next_due_at) WHERE active = TRUE;

CREATE TABLE IF NOT EXISTS client_practice_log (
    id              BIGSERIAL PRIMARY KEY,
    username        TEXT NOT NULL,
    practice_key    TEXT NOT NULL,
    focus_area      TEXT,
    completed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source          TEXT NOT NULL DEFAULT 'chat'
        CHECK (source IN ('chat', 'voice', 'email_reply', 'coach', 'app', 'auto')),
    harvest         TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_client_practice_log_user
    ON client_practice_log (username, completed_at DESC);

-- ── 3. In-house strengths inventory (VIA-tagged, free) ───────────────────
CREATE TABLE IF NOT EXISTS client_strengths (
    username        TEXT PRIMARY KEY REFERENCES users(username) ON DELETE CASCADE,
    via_top         TEXT[] NOT NULL DEFAULT '{}',
    clifton_domains TEXT[] NOT NULL DEFAULT '{}',
    answers         JSONB NOT NULL DEFAULT '[]'::jsonb,
    method          TEXT NOT NULL DEFAULT 'interview',
    assessed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── 4. Goals: reuse nate_commitments, add trajectory columns ─────────────
ALTER TABLE nate_commitments ADD COLUMN IF NOT EXISTS focus_area    TEXT;
ALTER TABLE nate_commitments ADD COLUMN IF NOT EXISTS started_at    TIMESTAMPTZ;
ALTER TABLE nate_commitments ADD COLUMN IF NOT EXISTS completed_at  TIMESTAMPTZ;
ALTER TABLE nate_commitments ADD COLUMN IF NOT EXISTS progress_pct  NUMERIC(5,2) NOT NULL DEFAULT 0;
ALTER TABLE nate_commitments ADD COLUMN IF NOT EXISTS growth_phase  TEXT;
-- LN-coached goals keep source='auto_extracted' (existing CHECK untouched) and
-- are distinguished by coached_by below.
ALTER TABLE nate_commitments ADD COLUMN IF NOT EXISTS coached_by    TEXT;

-- ── 5. LN entry greeting log ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ln_entry_greetings (
    id              BIGSERIAL PRIMARY KEY,
    username        TEXT NOT NULL,
    greeted_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    local_hour      SMALLINT,
    day_part        TEXT,
    growth_phase    TEXT,
    part_welcome    TEXT,
    part_prime      TEXT,
    part_direction  TEXT,
    thera_panel_id  TEXT,
    signals         JSONB NOT NULL DEFAULT '{}'::jsonb,
    delivered       BOOLEAN NOT NULL DEFAULT FALSE,
    opened          BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_ln_entry_greetings_user
    ON ln_entry_greetings (username, greeted_at DESC);

-- ── 6. Reminder log (email-only life-coach cadence) ──────────────────────
CREATE TABLE IF NOT EXISTS thrive_reminders (
    id              BIGSERIAL PRIMARY KEY,
    username        TEXT NOT NULL,
    practice_key    TEXT,
    commitment_id   UUID,
    reminder_type   TEXT NOT NULL
        CHECK (reminder_type IN ('practice_due', 'goal_checkpoint', 'goal_due',
                                 'weekly_recap', 'streak_celebration', 'phase_promoted')),
    channel         TEXT NOT NULL DEFAULT 'email',
    subject         TEXT,
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_thrive_reminders_user
    ON thrive_reminders (username, sent_at DESC);

COMMENT ON TABLE client_growth_phase IS
    'Growth-phase architecture: heal→thrive phase per client (stabilize/process/consolidate/thrive/generative) with working_through / crisis_hold sub-states. LN auto-promotes; coach notified.';
COMMENT ON TABLE client_focus_areas IS
    'Positive-psychology focus areas (PERMA/PTG) with anchor practice cadence; drives LN weaving + email reminders.';

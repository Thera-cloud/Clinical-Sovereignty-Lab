-- ============================================================================
-- Migration 222: clinical intake form
--
-- Client-owned intake answers used by:
-- - client self-service edits
-- - coach review/edit (section 2 only)
-- - Little Nate walkthrough credits (section 1 only)
-- ============================================================================

CREATE TABLE IF NOT EXISTS intake_form (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL UNIQUE,
    user_hardware_id TEXT,

    -- Section 1 (Little Nate + coach + client)
    q1_preferred_name TEXT,
    q2_pronouns TEXT,
    q3_household_relationship TEXT,
    q4_bringing_you_in TEXT,
    q5_how_long TEXT,
    q6_hope_to_get TEXT,
    q7_successful_outcome TEXT,
    q8_biggest_things_weighing TEXT,
    q9_support_network TEXT,
    q10_current_wellbeing TEXT,
    q11_communication_preferences TEXT,
    q12_anything_else_upfront TEXT,

    -- Section 2 (coach-only for Nate)
    q13_emergency_contact_name TEXT,
    q13_emergency_contact_phone TEXT,
    q14_address TEXT,
    q15_prior_treatment TEXT,
    q16_current_medications TEXT,
    q17_family_history TEXT,
    q18_suicide_self_harm_history TEXT,
    q19_trauma_history TEXT,
    q20_substance_use TEXT,
    q21_sleep_appetite_energy TEXT,

    section_1_status TEXT NOT NULL DEFAULT 'not_started',
    section_1_completed_at TIMESTAMPTZ,
    section_2_status TEXT NOT NULL DEFAULT 'not_started',
    section_2_completed_at TIMESTAMPTZ,
    section_2_completed_by TEXT,

    -- question_id -> true for walkthrough reward dedupe
    tokens_credited JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Coach-authored style guidance for Nate (non-clinical tone guidance)
    coach_nate_style_guidance TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT intake_form_s1_status_chk
        CHECK (section_1_status IN ('not_started', 'in_progress', 'complete')),
    CONSTRAINT intake_form_s2_status_chk
        CHECK (section_2_status IN ('not_started', 'in_progress', 'complete')),
    CONSTRAINT intake_form_s2_completed_by_chk
        CHECK (section_2_completed_by IS NULL OR section_2_completed_by IN ('client', 'coach')),
    CONSTRAINT intake_form_q9_chk
        CHECK (q9_support_network IS NULL OR q9_support_network IN ('yes', 'somewhat', 'no')),
    CONSTRAINT intake_form_q10_chk
        CHECK (q10_current_wellbeing IS NULL OR q10_current_wellbeing IN ('not_satisfactory', 'satisfactory', 'thriving'))
);

CREATE INDEX IF NOT EXISTS idx_intake_form_user_hardware_id
    ON intake_form (user_hardware_id);

CREATE INDEX IF NOT EXISTS idx_intake_form_section_status
    ON intake_form (section_1_status, section_2_status);

CREATE TABLE IF NOT EXISTS intake_form_audit (
    audit_id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    question_id TEXT NOT NULL,
    old_value JSONB,
    new_value JSONB,
    actor TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    method TEXT NOT NULL,
    override_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_intake_form_audit_user_id
    ON intake_form_audit (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_intake_form_audit_method
    ON intake_form_audit (method, created_at DESC);

CREATE TABLE IF NOT EXISTS intake_reminders (
    reminder_id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    coach_username TEXT NOT NULL,
    sections JSONB NOT NULL DEFAULT '[]'::jsonb,
    methods JSONB NOT NULL DEFAULT '[]'::jsonb,
    personal_note TEXT,
    override_rate_limit BOOLEAN NOT NULL DEFAULT FALSE,
    override_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_intake_reminders_user_id_sent_at
    ON intake_reminders (user_id, sent_at DESC);

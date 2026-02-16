-- Migration 027: Applied Solutions + Onboarding + Governance + Billing Tables
-- Supports S1-S10 solutions, onboarding flow, clinical governance, and metered billing.

-- =============================================================================
-- ONBOARDING
-- =============================================================================

CREATE TABLE IF NOT EXISTS onboarding_initiations (
    initiation_id   TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    email           TEXT,
    name            TEXT,
    subscription_tier TEXT DEFAULT 'threshold',
    stage           TEXT DEFAULT 'welcome',
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    abandoned_at    TIMESTAMPTZ,
    assigned_coach_id TEXT,
    metadata        JSONB DEFAULT '{}'::jsonb,
    CONSTRAINT fk_onboarding_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_onboarding_user ON onboarding_initiations(user_id);
CREATE INDEX IF NOT EXISTS idx_onboarding_stage ON onboarding_initiations(stage);

CREATE TABLE IF NOT EXISTS welcome_conversations (
    conversation_id TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    conversation_type TEXT DEFAULT 'casual',
    presenting_concern TEXT,
    initial_mood    TEXT,
    safety_flag     BOOLEAN DEFAULT FALSE,
    safety_flag_reason TEXT,
    goals           JSONB DEFAULT '[]'::jsonb,
    preferences     JSONB DEFAULT '{}'::jsonb,
    completed       BOOLEAN DEFAULT FALSE,
    duration_seconds INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT fk_welcome_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS welcome_turns (
    id              SERIAL PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES welcome_conversations(conversation_id) ON DELETE CASCADE,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    detected_themes JSONB DEFAULT '[]'::jsonb,
    detected_emotions JSONB DEFAULT '[]'::jsonb,
    pii_redacted    BOOLEAN DEFAULT FALSE,
    timestamp       TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS nevedal_cold_starts (
    user_id         TEXT PRIMARY KEY,
    voice_sample_collected BOOLEAN DEFAULT FALSE,
    text_exchanges  INTEGER DEFAULT 0,
    computed_p_ent  FLOAT DEFAULT 0.5,
    computed_gamma_env FLOAT DEFAULT 0.5,
    computed_t_tunnel FLOAT DEFAULT 0.3,
    cold_start_c_emo FLOAT DEFAULT 0.0,
    initial_pitch_mean FLOAT DEFAULT 0.0,
    initial_pitch_variance FLOAT DEFAULT 0.0,
    initial_energy FLOAT DEFAULT 0.0,
    initial_speech_rate FLOAT DEFAULT 0.0,
    initial_pause_ratio FLOAT DEFAULT 0.0,
    baseline_established BOOLEAN DEFAULT FALSE,
    calibration_confidence FLOAT DEFAULT 0.0,
    initiated_at    TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT fk_cold_start_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- =============================================================================
-- SILENT CRISIS (S1)
-- =============================================================================

CREATE TABLE IF NOT EXISTS silent_alerts (
    alert_id        TEXT PRIMARY KEY,
    member_id       TEXT NOT NULL,
    alert_level     TEXT NOT NULL,
    hours_silent    FLOAT DEFAULT 0,
    last_known_c_emo FLOAT DEFAULT 0,
    c_emo_trajectory TEXT DEFAULT 'unknown',
    recommended_action TEXT DEFAULT 'gentle_checkin',
    cosmic_ring_partners JSONB DEFAULT '[]'::jsonb,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ,
    resolved_by     TEXT
);

CREATE INDEX IF NOT EXISTS idx_silent_alerts_member ON silent_alerts(member_id);
CREATE INDEX IF NOT EXISTS idx_silent_alerts_level ON silent_alerts(alert_level);

-- =============================================================================
-- EMOTIONAL WEATHER (S2)
-- =============================================================================

CREATE TABLE IF NOT EXISTS emotional_weather_snapshots (
    id              SERIAL PRIMARY KEY,
    sanctuary_id    TEXT NOT NULL,
    family_id       TEXT NOT NULL,
    member_states   JSONB DEFAULT '{}'::jsonb,
    dyad_coherence  JSONB DEFAULT '{}'::jsonb,
    system_coherence FLOAT DEFAULT 0,
    system_volatility FLOAT DEFAULT 0,
    cee_window_open BOOLEAN DEFAULT FALSE,
    bridge_member   TEXT,
    isolated_member TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_weather_sanctuary ON emotional_weather_snapshots(sanctuary_id);
CREATE INDEX IF NOT EXISTS idx_weather_family ON emotional_weather_snapshots(family_id);

-- =============================================================================
-- PREDICTIVE COACH BRIEFINGS (S3)
-- =============================================================================

CREATE TABLE IF NOT EXISTS coach_briefings (
    briefing_id     TEXT PRIMARY KEY,
    coach_id        TEXT NOT NULL,
    member_id       TEXT NOT NULL,
    member_name     TEXT,
    session_datetime TIMESTAMPTZ,
    briefing_data   JSONB DEFAULT '{}'::jsonb,
    acknowledged    BOOLEAN DEFAULT FALSE,
    acknowledged_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_briefings_coach ON coach_briefings(coach_id);
CREATE INDEX IF NOT EXISTS idx_briefings_session ON coach_briefings(session_datetime);

-- =============================================================================
-- COMMUNITY EARLY WARNING (S5)
-- =============================================================================

CREATE TABLE IF NOT EXISTS cultural_signals (
    signal_id       TEXT PRIMARY KEY,
    source_platform TEXT,
    signal_type     TEXT,
    description     TEXT,
    keywords        JSONB DEFAULT '[]'::jsonb,
    sentiment       FLOAT DEFAULT 0,
    volume          INTEGER DEFAULT 0,
    velocity        FLOAT DEFAULT 0,
    geographic_scope TEXT DEFAULT 'national',
    confidence      FLOAT DEFAULT 0,
    first_detected  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS community_warnings (
    warning_id      TEXT PRIMARY KEY,
    signal_id       TEXT REFERENCES cultural_signals(signal_id),
    affected_members JSONB DEFAULT '[]'::jsonb,
    total_families_affected INTEGER DEFAULT 0,
    severity        TEXT DEFAULT 'advisory',
    coach_alerts    JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================================
-- COACH RECRUITMENT (S6)
-- =============================================================================

CREATE TABLE IF NOT EXISTS coach_recruitment_campaigns (
    campaign_id     TEXT PRIMARY KEY,
    target_specialty TEXT,
    target_platforms JSONB DEFAULT '[]'::jsonb,
    autonomy_level  TEXT DEFAULT 'observation',
    approval_required BOOLEAN DEFAULT TRUE,
    impressions     INTEGER DEFAULT 0,
    engagements     INTEGER DEFAULT 0,
    quiz_starts     INTEGER DEFAULT 0,
    quiz_completions INTEGER DEFAULT 0,
    golden_tickets_sent INTEGER DEFAULT 0,
    coaches_onboarded INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS coach_assessment_results (
    quiz_id         TEXT PRIMARY KEY,
    prospect_name   TEXT,
    prospect_email  TEXT,
    therapeutic_orientation JSONB DEFAULT '{}'::jsonb,
    ai_comfort_level FLOAT DEFAULT 0,
    platform_fit_score FLOAT DEFAULT 0,
    match_score     FLOAT DEFAULT 0,
    golden_ticket_eligible BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================================
-- GRADUATED AUTONOMY (S8)
-- =============================================================================

CREATE TABLE IF NOT EXISTS fibre_autonomy_audit (
    id              SERIAL PRIMARY KEY,
    fibre_id        TEXT NOT NULL,
    fibre_type      TEXT,
    current_level   TEXT DEFAULT 'observation',
    total_proposals INTEGER DEFAULT 0,
    approved_proposals INTEGER DEFAULT 0,
    rejected_proposals INTEGER DEFAULT 0,
    total_autonomous_actions INTEGER DEFAULT 0,
    successful_actions INTEGER DEFAULT 0,
    failed_actions  INTEGER DEFAULT 0,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_autonomy_fibre ON fibre_autonomy_audit(fibre_id);

-- =============================================================================
-- TRANSGENERATIONAL PATTERNS (S9)
-- =============================================================================

CREATE TABLE IF NOT EXISTS transgenerational_patterns (
    pattern_id      TEXT PRIMARY KEY,
    pattern_name    TEXT,
    description     TEXT,
    families_observed INTEGER DEFAULT 0,
    confidence      FLOAT DEFAULT 0,
    p_value         FLOAT DEFAULT 1.0,
    effect_size     FLOAT DEFAULT 0,
    early_indicators JSONB DEFAULT '[]'::jsonb,
    anonymization_verified BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================================
-- CLINICAL GOVERNANCE
-- =============================================================================

CREATE TABLE IF NOT EXISTS scope_violation_logs (
    log_id          TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    session_id      TEXT,
    boundary_type   TEXT NOT NULL,
    trigger_content TEXT,
    nate_response   TEXT,
    escalated_to    TEXT,
    timestamp       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scope_violations_user ON scope_violation_logs(user_id);

CREATE TABLE IF NOT EXISTS mandatory_reporting_protocols (
    protocol_id     TEXT PRIMARY KEY,
    trigger         TEXT NOT NULL,
    detection_source TEXT,
    user_id         TEXT NOT NULL,
    session_id      TEXT,
    coach_id        TEXT,
    severity        TEXT DEFAULT 'high',
    coach_notified  BOOLEAN DEFAULT FALSE,
    supervisor_notified BOOLEAN DEFAULT FALSE,
    report_filed    BOOLEAN DEFAULT FALSE,
    report_filed_at TIMESTAMPTZ,
    audit_trail     JSONB DEFAULT '[]'::jsonb,
    detected_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS clinical_records (
    record_id       TEXT PRIMARY KEY,
    record_type     TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    coach_id        TEXT,
    session_id      TEXT,
    content         TEXT DEFAULT '',
    ai_generated    BOOLEAN DEFAULT FALSE,
    coach_reviewed  BOOLEAN DEFAULT FALSE,
    coach_reviewed_at TIMESTAMPTZ,
    retention_period_years INTEGER DEFAULT 7,
    encrypted       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_clinical_records_user ON clinical_records(user_id);
CREATE INDEX IF NOT EXISTS idx_clinical_records_type ON clinical_records(record_type);

-- =============================================================================
-- METERED BILLING
-- =============================================================================

CREATE TABLE IF NOT EXISTS usage_records (
    record_id       TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    usage_type      TEXT NOT NULL,
    quantity         FLOAT DEFAULT 0,
    unit_cost       FLOAT DEFAULT 0,
    total_cost      FLOAT DEFAULT 0,
    session_id      TEXT,
    stripe_usage_record_id TEXT,
    reported_to_stripe BOOLEAN DEFAULT FALSE,
    timestamp       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_usage_user ON usage_records(user_id);
CREATE INDEX IF NOT EXISTS idx_usage_type ON usage_records(usage_type);
CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON usage_records(timestamp);

CREATE TABLE IF NOT EXISTS metered_billing_state (
    user_id         TEXT PRIMARY KEY,
    billing_tier    TEXT DEFAULT 'threshold',
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    included_ai_minutes FLOAT DEFAULT 0,
    used_ai_minutes FLOAT DEFAULT 0,
    included_coach_sessions INTEGER DEFAULT 0,
    used_coach_sessions INTEGER DEFAULT 0,
    overage_charges FLOAT DEFAULT 0,
    session_cost_cap FLOAT DEFAULT 500,
    session_cost_cap_hit BOOLEAN DEFAULT FALSE,
    billing_period_start TIMESTAMPTZ,
    billing_period_end TIMESTAMPTZ,
    CONSTRAINT fk_billing_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cost_threshold_configs (
    user_id         TEXT PRIMARY KEY,
    per_session_cap FLOAT DEFAULT 500,
    monthly_cap     FLOAT DEFAULT 2000,
    warning_threshold_pct FLOAT DEFAULT 0.8,
    hard_stop_enabled BOOLEAN DEFAULT TRUE,
    overage_allowed BOOLEAN DEFAULT FALSE,
    CONSTRAINT fk_cost_threshold_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

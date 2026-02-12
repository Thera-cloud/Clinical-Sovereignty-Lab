-- =============================================================================
-- LITTLE NATE — Drip Campaign System Schema
-- Version: 2.0
-- Date: February 2026
-- Depends on: 001_schema.sql
-- =============================================================================

-- =============================================================================
-- CAMPAIGNS: Top-level drip campaign definitions
-- =============================================================================
CREATE TABLE campaigns (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(200) NOT NULL,
    description TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'active', 'paused', 'archived')),
    conversion_window_days INTEGER DEFAULT 7,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TRIGGER campaigns_updated_at BEFORE UPDATE ON campaigns
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- =============================================================================
-- CAMPAIGN_STEPS: Ordered steps within a campaign (email + optional quiz)
-- =============================================================================
CREATE TABLE campaign_steps (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL,
    delay_hours INTEGER NOT NULL DEFAULT 24,

    -- Email content
    email_subject VARCHAR(500),
    email_body TEXT,
    email_template_id VARCHAR(100),        -- SendGrid dynamic template ID

    -- Quiz linkage (optional per step)
    quiz_id UUID,                           -- FK added after quizzes table

    -- SMS fallback
    sms_enabled BOOLEAN DEFAULT FALSE,
    sms_template TEXT,
    sms_fallback_delay_hours INTEGER DEFAULT 4,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (campaign_id, step_order)
);

CREATE TRIGGER campaign_steps_updated_at BEFORE UPDATE ON campaign_steps
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- =============================================================================
-- QUIZZES: Quiz definitions (5 quizzes in the Emotional Coherence journey)
-- =============================================================================
CREATE TABLE quizzes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title VARCHAR(200) NOT NULL,
    description TEXT,
    theme VARCHAR(100),                     -- e.g., "Emotional Awareness"
    dimension VARCHAR(100),                 -- e.g., "self_awareness"
    quiz_order INTEGER NOT NULL,            -- 1-5 in the journey
    is_final BOOLEAN DEFAULT FALSE,         -- True for Quiz 5

    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TRIGGER quizzes_updated_at BEFORE UPDATE ON quizzes
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Add FK from campaign_steps to quizzes
ALTER TABLE campaign_steps
    ADD CONSTRAINT fk_campaign_steps_quiz
    FOREIGN KEY (quiz_id) REFERENCES quizzes(id) ON DELETE SET NULL;

-- =============================================================================
-- QUIZ_QUESTIONS: Individual questions within a quiz
-- =============================================================================
CREATE TABLE quiz_questions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    quiz_id UUID NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    question_order INTEGER NOT NULL,
    question_text TEXT NOT NULL,
    question_type VARCHAR(30) NOT NULL
        CHECK (question_type IN ('scale', 'multiple_choice', 'multi_select', 'ranking', 'open_text')),

    -- Options for choice-based questions (JSONB array)
    options JSONB DEFAULT '[]',
    /*
    Example options for multiple_choice:
    [
        {"value": "a", "label": "Strongly disagree"},
        {"value": "b", "label": "Disagree"},
        {"value": "c", "label": "Neutral"},
        {"value": "d", "label": "Agree"},
        {"value": "e", "label": "Strongly agree"}
    ]
    */

    -- Scale configuration (for 'scale' type)
    scale_min INTEGER DEFAULT 1,
    scale_max INTEGER DEFAULT 10,
    scale_min_label VARCHAR(100),
    scale_max_label VARCHAR(100),

    -- Tagging for analysis
    dimension_tag VARCHAR(100),             -- Maps to insight dimensions

    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (quiz_id, question_order)
);

-- =============================================================================
-- PROSPECTS: People going through the drip funnel (not yet clients)
-- =============================================================================
CREATE TABLE prospects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    phone VARCHAR(30),
    source VARCHAR(100),                    -- 'website', 'linkedin', 'referral', 'import'

    -- Journey status
    status VARCHAR(30) NOT NULL DEFAULT 'subscribed'
        CHECK (status IN (
            'subscribed',                   -- Just signed up
            'active_journey',               -- Going through drip steps
            'quiz_complete',                -- Completed all 5 quizzes
            'golden_ticket_issued',         -- Assessment ready, ticket sent
            'redeemed',                     -- Ticket redeemed, account created
            'converted',                    -- Paying client
            'lapsed',                       -- Ticket expired without redemption
            'unsubscribed'                  -- Opted out
        )),

    -- Campaign progress
    current_campaign_id UUID REFERENCES campaigns(id) ON DELETE SET NULL,
    current_step INTEGER DEFAULT 0,
    next_email_at TIMESTAMP WITH TIME ZONE,
    journey_started_at TIMESTAMP WITH TIME ZONE,
    journey_completed_at TIMESTAMP WITH TIME ZONE,

    -- Golden Ticket fields
    golden_ticket_token VARCHAR(64) UNIQUE,
    golden_ticket_issued_at TIMESTAMP WITH TIME ZONE,
    golden_ticket_expires_at TIMESTAMP WITH TIME ZONE,
    golden_ticket_redeemed_at TIMESTAMP WITH TIME ZONE,

    -- Conversion tracking
    converted_to_client_id UUID REFERENCES users(id) ON DELETE SET NULL,
    converted_at TIMESTAMP WITH TIME ZONE,

    -- Opt-out
    sms_opt_out BOOLEAN DEFAULT FALSE,
    email_opt_out BOOLEAN DEFAULT FALSE,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TRIGGER prospects_updated_at BEFORE UPDATE ON prospects
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE INDEX idx_prospects_status ON prospects(status);
CREATE INDEX idx_prospects_next_email ON prospects(next_email_at)
    WHERE next_email_at IS NOT NULL AND status = 'active_journey';
CREATE INDEX idx_prospects_campaign ON prospects(current_campaign_id, current_step);
CREATE INDEX idx_prospects_ticket ON prospects(golden_ticket_token)
    WHERE golden_ticket_token IS NOT NULL;

-- =============================================================================
-- QUIZ_RESPONSES: Prospect answers to quiz questions
-- =============================================================================
CREATE TABLE quiz_responses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    prospect_id UUID NOT NULL REFERENCES prospects(id) ON DELETE CASCADE,
    quiz_id UUID NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    campaign_id UUID REFERENCES campaigns(id) ON DELETE SET NULL,

    -- Responses stored as JSONB array
    responses JSONB NOT NULL DEFAULT '[]',
    /*
    Example:
    [
        {"question_id": "uuid", "question_order": 1, "answer": 7, "type": "scale"},
        {"question_id": "uuid", "question_order": 2, "answer": "c", "type": "multiple_choice"},
        {"question_id": "uuid", "question_order": 3, "answer": ["a","c","e"], "type": "multi_select"},
        {"question_id": "uuid", "question_order": 4, "answer": "I feel most alive when...", "type": "open_text"}
    ]
    */

    -- Timing
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    duration_seconds INTEGER,

    -- Insight generated flag
    insight_generated BOOLEAN DEFAULT FALSE,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (prospect_id, quiz_id)
);

CREATE INDEX idx_quiz_responses_prospect ON quiz_responses(prospect_id, completed_at DESC);

-- =============================================================================
-- NATE_INSIGHTS: Little Nate's personalized analysis per quiz
-- =============================================================================
CREATE TABLE nate_insights (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    prospect_id UUID NOT NULL REFERENCES prospects(id) ON DELETE CASCADE,
    quiz_id UUID NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,

    -- Insight content
    insight_text TEXT NOT NULL,              -- The personalized insight paragraph
    patterns JSONB DEFAULT '[]',            -- Detected emotional patterns
    strength VARCHAR(200),                  -- Primary strength identified
    growth_area VARCHAR(200),               -- Primary growth area identified

    -- Cumulative narrative (updated each quiz)
    cumulative_narrative TEXT,

    -- Metadata
    model_used VARCHAR(100),                -- e.g., "gpt-4o"
    tokens_used INTEGER,
    generation_time_ms INTEGER,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (prospect_id, quiz_id)
);

CREATE INDEX idx_nate_insights_prospect ON nate_insights(prospect_id, created_at DESC);

-- =============================================================================
-- COACHING_ASSESSMENTS: Full assessment generated after Quiz 5
-- =============================================================================
CREATE TABLE coaching_assessments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    prospect_id UUID UNIQUE NOT NULL REFERENCES prospects(id) ON DELETE CASCADE,

    -- Assessment content
    snapshot TEXT NOT NULL,                  -- Comprehensive emotional profile
    goals JSONB DEFAULT '[]',               -- Array of 3 coaching goals
    /*
    Example goals:
    [
        {"title": "Emotional Regulation", "description": "...", "priority": 1},
        {"title": "Boundary Setting", "description": "...", "priority": 2},
        {"title": "Self-Compassion Practice", "description": "...", "priority": 3}
    ]
    */
    legacy_statement TEXT,                  -- The aspirational "legacy" statement

    -- Migration tracking
    migrated_to_vault BOOLEAN DEFAULT FALSE,
    migrated_at TIMESTAMP WITH TIME ZONE,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- PROSPECT_STORY_STORE: Cumulative narrative built across all quizzes
-- =============================================================================
CREATE TABLE prospect_story_store (
    prospect_id UUID PRIMARY KEY REFERENCES prospects(id) ON DELETE CASCADE,

    -- Running narrative
    cumulative_narrative TEXT DEFAULT '',
    patterns JSONB DEFAULT '[]',            -- Aggregated patterns across quizzes
    emotional_profile JSONB DEFAULT '{}',   -- Structured profile data
    /*
    Example emotional_profile:
    {
        "dominant_emotions": ["curiosity", "anxiety"],
        "attachment_style": "anxious-secure",
        "communication_preference": "reflective",
        "growth_trajectory": "ascending",
        "coherence_indicators": {"self_awareness": 0.72, "regulation": 0.58}
    }
    */

    -- Progress
    last_quiz_completed INTEGER DEFAULT 0,  -- 0-5
    quizzes_completed INTEGER DEFAULT 0,

    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TRIGGER prospect_story_store_updated_at BEFORE UPDATE ON prospect_story_store
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- =============================================================================
-- DELIVERY_LOG: Email and SMS delivery tracking
-- =============================================================================
CREATE TABLE delivery_log (
    id BIGSERIAL PRIMARY KEY,
    prospect_id UUID NOT NULL REFERENCES prospects(id) ON DELETE CASCADE,

    -- Delivery details
    channel VARCHAR(10) NOT NULL CHECK (channel IN ('email', 'sms')),
    message_type VARCHAR(50),               -- 'drip_day_1', 'insight', 'golden_ticket', 'reminder'
    provider_message_id VARCHAR(200),       -- SendGrid message ID or Twilio SID

    -- Status tracking
    status VARCHAR(20) NOT NULL DEFAULT 'sent'
        CHECK (status IN ('queued', 'sent', 'delivered', 'opened', 'clicked', 'bounced', 'failed', 'unsubscribed')),

    -- Timestamps
    sent_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    delivered_at TIMESTAMP WITH TIME ZONE,
    opened_at TIMESTAMP WITH TIME ZONE,
    clicked_at TIMESTAMP WITH TIME ZONE,
    failed_at TIMESTAMP WITH TIME ZONE,
    failure_reason TEXT,

    -- Content reference
    campaign_step_id UUID REFERENCES campaign_steps(id) ON DELETE SET NULL,
    subject VARCHAR(500),
    template_id VARCHAR(100)
);

CREATE INDEX idx_delivery_log_prospect ON delivery_log(prospect_id, sent_at DESC);
CREATE INDEX idx_delivery_log_status ON delivery_log(status, sent_at);
CREATE INDEX idx_delivery_log_provider ON delivery_log(provider_message_id);

-- =============================================================================
-- CAMPAIGN_ANALYTICS: Daily aggregated campaign metrics
-- =============================================================================
CREATE TABLE campaign_analytics (
    id BIGSERIAL PRIMARY KEY,
    campaign_id UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    date DATE NOT NULL,

    -- Counts
    emails_sent INTEGER DEFAULT 0,
    emails_delivered INTEGER DEFAULT 0,
    emails_opened INTEGER DEFAULT 0,
    emails_clicked INTEGER DEFAULT 0,
    emails_bounced INTEGER DEFAULT 0,
    sms_sent INTEGER DEFAULT 0,
    sms_delivered INTEGER DEFAULT 0,
    quizzes_started INTEGER DEFAULT 0,
    quizzes_completed INTEGER DEFAULT 0,
    insights_generated INTEGER DEFAULT 0,
    tickets_issued INTEGER DEFAULT 0,
    tickets_redeemed INTEGER DEFAULT 0,
    conversions INTEGER DEFAULT 0,

    -- Rates (computed, stored for fast queries)
    open_rate DECIMAL(5,4) DEFAULT 0,
    click_rate DECIMAL(5,4) DEFAULT 0,
    quiz_completion_rate DECIMAL(5,4) DEFAULT 0,
    conversion_rate DECIMAL(5,4) DEFAULT 0,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (campaign_id, date)
);

CREATE INDEX idx_campaign_analytics_date ON campaign_analytics(campaign_id, date DESC);

-- =============================================================================
-- VIEWS
-- =============================================================================

-- Campaign overview with prospect counts
CREATE VIEW v_campaign_overview AS
SELECT
    c.id,
    c.name,
    c.status,
    c.conversion_window_days,
    c.created_at,
    COUNT(DISTINCT p.id) AS total_prospects,
    COUNT(DISTINCT CASE WHEN p.status = 'active_journey' THEN p.id END) AS active_prospects,
    COUNT(DISTINCT CASE WHEN p.status = 'converted' THEN p.id END) AS converted_prospects,
    COUNT(DISTINCT CASE WHEN p.status = 'golden_ticket_issued' THEN p.id END) AS pending_tickets,
    COUNT(DISTINCT qr.id) AS total_quiz_responses
FROM campaigns c
LEFT JOIN prospects p ON p.current_campaign_id = c.id
LEFT JOIN quiz_responses qr ON qr.campaign_id = c.id
GROUP BY c.id, c.name, c.status, c.conversion_window_days, c.created_at;

-- Prospect journey view (full status at a glance)
CREATE VIEW v_prospect_journey AS
SELECT
    p.id,
    p.email,
    p.first_name,
    p.last_name,
    p.status,
    p.source,
    p.current_step,
    p.journey_started_at,
    c.name AS campaign_name,
    ss.last_quiz_completed,
    ss.quizzes_completed,
    (SELECT COUNT(*) FROM nate_insights ni WHERE ni.prospect_id = p.id) AS insights_count,
    p.golden_ticket_token IS NOT NULL AS has_ticket,
    p.golden_ticket_expires_at,
    p.converted_at,
    p.created_at
FROM prospects p
LEFT JOIN campaigns c ON c.id = p.current_campaign_id
LEFT JOIN prospect_story_store ss ON ss.prospect_id = p.id;

-- =============================================================================
-- END OF DRIP CAMPAIGN SCHEMA
-- =============================================================================

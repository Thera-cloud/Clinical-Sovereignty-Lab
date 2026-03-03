-- Migration 078: Check-In Wisdom + Coach Nate Progress Tables
-- Supports the Check-In Reply Pipeline and Coach Nate DOJO cumulative tracking.

-- Per-user check-in response storage (SMS/email replies to Little Nate's 72h outreach)
CREATE TABLE IF NOT EXISTS checkin_wisdom (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    role VARCHAR(10) NOT NULL,
    checkin_id UUID REFERENCES nate_checkins(id),
    channel VARCHAR(10) CHECK (channel IN ('sms', 'email')),
    response_text TEXT NOT NULL,
    extracted_insights JSONB DEFAULT '{}',
    ai_summary TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_checkin_wisdom_user ON checkin_wisdom(user_id, created_at DESC);

-- Coach Nate DOJO cumulative progress per skill area
CREATE TABLE IF NOT EXISTS coach_nate_progress (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    coach_username VARCHAR(64) NOT NULL,
    skill_area VARCHAR(32) NOT NULL CHECK (skill_area IN (
        'rapport_building', 'focused_listening', 'intuition_development',
        'effective_questions', 'constructive_feedback', 'coaching_path'
    )),
    session_count INTEGER DEFAULT 0,
    total_score NUMERIC(6,2) DEFAULT 0,
    average_score NUMERIC(5,2) DEFAULT 0,
    best_score NUMERIC(5,2) DEFAULT 0,
    dimension_averages JSONB DEFAULT '{}',
    last_session_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(coach_username, skill_area)
);
CREATE INDEX IF NOT EXISTS idx_coach_nate_progress_coach ON coach_nate_progress(coach_username);

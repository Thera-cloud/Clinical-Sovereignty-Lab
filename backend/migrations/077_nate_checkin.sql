-- Migration 077: Nate Check-In Agent
-- Tracks 72-hour inactivity outreach for clients and coaches

CREATE TABLE IF NOT EXISTS nate_checkins (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    role VARCHAR(10) NOT NULL CHECK (role IN ('CLIENT', 'COACH')),
    checkin_type VARCHAR(32) NOT NULL CHECK (checkin_type IN (
        'coach_alert_62h', 'client_72h', 'coach_72h'
    )),
    channel VARCHAR(10) CHECK (channel IN ('sms', 'email')),
    content TEXT,
    status VARCHAR(20) DEFAULT 'sent' CHECK (status IN (
        'sent', 'responded', 'snoozed', 'expired'
    )),
    snooze_days INTEGER CHECK (snooze_days BETWEEN 1 AND 3),
    snooze_until TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    responded_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_checkins_user ON nate_checkins(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_checkins_status ON nate_checkins(status, snooze_until);
CREATE INDEX IF NOT EXISTS idx_checkins_type_recent ON nate_checkins(checkin_type, created_at DESC);

-- 058: Engagement Requests table for Tier 3 approval-gated social actions
-- Little Nate creates requests; admin approves/rejects via SkyEye UI

CREATE TABLE IF NOT EXISTS engagement_requests (
    id              SERIAL PRIMARY KEY,
    platform        TEXT NOT NULL,
    action_type     TEXT NOT NULL,
    target_user     TEXT,
    target_user_id  TEXT,
    content_preview TEXT NOT NULL,
    reason          TEXT,
    context         JSONB,
    status          TEXT NOT NULL DEFAULT 'pending',
    priority        TEXT NOT NULL DEFAULT 'normal',
    session_id      INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '48 hours'),
    resolved_at     TIMESTAMPTZ,
    resolved_by     TEXT
);

CREATE INDEX IF NOT EXISTS idx_engagement_requests_status ON engagement_requests(status);
CREATE INDEX IF NOT EXISTS idx_engagement_requests_platform ON engagement_requests(platform);

-- Session settings for 3x 30-min sessions
INSERT INTO skyeye_settings (key, value) VALUES
    ('session_max_duration_minutes', '30'),
    ('max_sessions_per_day', '3')
ON CONFLICT DO NOTHING;

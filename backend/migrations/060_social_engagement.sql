-- Migration 060: Social Engagement Infrastructure
-- Adds tables for notification tracking, follower delta detection,
-- and per-post analytics used by the Notification Observer agent
-- and the session engine's React phase.

-- Engagement notifications detected by the Notification Observer
CREATE TABLE IF NOT EXISTS skyeye_notifications (
    id SERIAL PRIMARY KEY,
    platform VARCHAR(32) NOT NULL,
    notification_type VARCHAR(32) NOT NULL,
    post_id VARCHAR(128),
    actor_handle VARCHAR(128) NOT NULL,
    actor_id VARCHAR(128),
    actor_bio TEXT,
    actor_followers INTEGER,
    processed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notifications_unprocessed
    ON skyeye_notifications (processed, created_at DESC) WHERE NOT processed;

CREATE UNIQUE INDEX IF NOT EXISTS idx_notifications_dedup
    ON skyeye_notifications (platform, notification_type, COALESCE(post_id, ''), actor_handle);

-- Follower count snapshots for delta tracking (LinkedIn, etc.)
CREATE TABLE IF NOT EXISTS skyeye_follower_snapshots (
    id SERIAL PRIMARY KEY,
    platform VARCHAR(32) NOT NULL,
    follower_count INTEGER NOT NULL,
    captured_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_follower_snapshots_platform
    ON skyeye_follower_snapshots (platform, captured_at DESC);

-- Per-post performance metrics captured over time
CREATE TABLE IF NOT EXISTS skyeye_post_analytics (
    id SERIAL PRIMARY KEY,
    platform VARCHAR(32) NOT NULL,
    post_id VARCHAR(128) NOT NULL,
    post_url TEXT,
    post_text TEXT,
    likes INTEGER DEFAULT 0,
    reposts INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    impressions INTEGER DEFAULT 0,
    captured_at TIMESTAMPTZ DEFAULT NOW(),
    captured_date DATE DEFAULT CURRENT_DATE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_post_analytics_unique
    ON skyeye_post_analytics (platform, post_id, captured_date);

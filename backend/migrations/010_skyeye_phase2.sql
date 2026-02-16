-- =============================================================================
-- SKYEYE PHASE 2 — Autonomous Social Media Operations
-- Migration 010: Content Queue + Platform OAuth Tokens (renumbered from 005)
-- =============================================================================

BEGIN;

-- 1. CONTENT QUEUE — draft/scheduled/posted content pipeline
-- Little Nate generates content, it queues here for review or auto-posting
CREATE TABLE IF NOT EXISTS skyeye_content_queue (
    id              SERIAL PRIMARY KEY,
    platform        TEXT NOT NULL,                  -- target platform name (matches skyeye_platforms.name)
    content_text    TEXT NOT NULL,                  -- the post text in Little Nate's voice
    media_url       TEXT,                           -- optional media attachment URL
    content_type    TEXT NOT NULL DEFAULT 'post',   -- post/reply/cross_promo/expression
    emotion_context TEXT,                           -- emotion tag if derived from expression
    source_expression_id INT,                       -- FK to skyeye_live_expressions if applicable
    status          TEXT NOT NULL DEFAULT 'draft',  -- draft/scheduled/approved/posted/failed/rejected
    priority        TEXT NOT NULL DEFAULT 'normal', -- low/normal/high/urgent
    scheduled_for   TIMESTAMPTZ,                    -- when to publish (NULL = ASAP when approved)
    posted_at       TIMESTAMPTZ,                    -- when actually posted
    post_id_external TEXT,                          -- platform's native post ID after publishing
    post_url        TEXT,                           -- direct URL to the published post
    error_message   TEXT,                           -- error details if status='failed'
    generated_by    TEXT DEFAULT 'session_engine',  -- session_engine/admin/chat
    approved_by     TEXT,                           -- admin/auto (based on control_mode)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_content_queue_status ON skyeye_content_queue(status);
CREATE INDEX IF NOT EXISTS idx_content_queue_platform ON skyeye_content_queue(platform);
CREATE INDEX IF NOT EXISTS idx_content_queue_scheduled ON skyeye_content_queue(scheduled_for)
    WHERE status = 'scheduled';
CREATE INDEX IF NOT EXISTS idx_content_queue_created ON skyeye_content_queue(created_at DESC);

-- 2. PLATFORM TOKENS — OAuth access/refresh tokens for each connected platform
-- Stored encrypted at rest (application-level encryption before INSERT)
CREATE TABLE IF NOT EXISTS skyeye_platform_tokens (
    id              SERIAL PRIMARY KEY,
    platform        TEXT NOT NULL UNIQUE,            -- matches skyeye_platforms.name
    access_token    TEXT,                            -- encrypted OAuth access token
    refresh_token   TEXT,                            -- encrypted OAuth refresh token
    token_type      TEXT DEFAULT 'bearer',
    token_expiry    TIMESTAMPTZ,                     -- when the access token expires
    scopes          TEXT,                            -- granted OAuth scopes (comma-separated)
    account_id      TEXT,                            -- platform-specific account/page ID
    account_name    TEXT,                            -- display name on the platform
    last_refreshed  TIMESTAMPTZ,
    last_used       TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'disconnected', -- connected/disconnected/expired/revoked/error
    error_message   TEXT,                            -- last auth error if any
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_platform_tokens_status ON skyeye_platform_tokens(status);

-- 3. SESSION ACTIONS — granular per-action log during autonomous sessions
-- More detailed than skyeye_history — captures every single thing Little Nate does
CREATE TABLE IF NOT EXISTS skyeye_session_actions (
    id              SERIAL PRIMARY KEY,
    session_id      INT REFERENCES skyeye_sessions(id),
    platform        TEXT NOT NULL,
    phase           TEXT NOT NULL,                   -- wake/browse/observe/engage/moderate/create/post/rest
    action_type     TEXT NOT NULL,                   -- read_feed/read_comments/reply/post/delete/hide/block/detect_bot/detect_threat/etc.
    target_id       TEXT,                            -- platform-specific ID of the thing acted on
    target_user     TEXT,                            -- handle of the user involved (if any)
    detail          JSONB DEFAULT '{}',              -- flexible metadata (comment text, bot score, etc.)
    result          TEXT DEFAULT 'success',          -- success/failed/skipped/escalated
    duration_ms     INT,                             -- how long this action took
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_session_actions_session ON skyeye_session_actions(session_id);
CREATE INDEX IF NOT EXISTS idx_session_actions_platform ON skyeye_session_actions(platform);
CREATE INDEX IF NOT EXISTS idx_session_actions_created ON skyeye_session_actions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_session_actions_type ON skyeye_session_actions(action_type);

-- 4. Seed platform tokens rows (disconnected) for all 7 platforms
INSERT INTO skyeye_platform_tokens (platform, status)
VALUES
    ('tiktok',    'disconnected'),
    ('instagram', 'disconnected'),
    ('youtube',   'disconnected'),
    ('reddit',    'disconnected'),
    ('linkedin',  'disconnected'),
    ('facebook',  'disconnected'),
    ('pinterest', 'disconnected')
ON CONFLICT (platform) DO NOTHING;

-- 5. Add session scheduling settings to skyeye_settings
INSERT INTO skyeye_settings (key, value, platform)
VALUES
    -- Global session settings
    ('session_max_duration_minutes', '15', NULL),
    ('session_cooldown_minutes', '30', NULL),
    ('content_auto_approve_threshold', 'approval', NULL),   -- full/approval/observation (matches control_mode)
    -- Per-platform session frequency (sessions per day)
    ('sessions_per_day', '3', 'tiktok'),
    ('sessions_per_day', '3', 'instagram'),
    ('sessions_per_day', '2', 'youtube'),
    ('sessions_per_day', '2', 'reddit'),
    ('sessions_per_day', '1', 'linkedin'),
    ('sessions_per_day', '1', 'facebook'),
    ('sessions_per_day', '1', 'pinterest'),
    -- Per-platform max actions per session
    ('max_actions_per_session', '20', 'tiktok'),
    ('max_actions_per_session', '20', 'instagram'),
    ('max_actions_per_session', '15', 'youtube'),
    ('max_actions_per_session', '15', 'reddit'),
    ('max_actions_per_session', '10', 'linkedin'),
    ('max_actions_per_session', '10', 'facebook'),
    ('max_actions_per_session', '10', 'pinterest'),
    -- Per-platform rate limits (min seconds between actions)
    ('rate_limit_seconds', '10', 'tiktok'),
    ('rate_limit_seconds', '10', 'instagram'),
    ('rate_limit_seconds', '15', 'youtube'),
    ('rate_limit_seconds', '8', 'reddit'),
    ('rate_limit_seconds', '20', 'linkedin'),
    ('rate_limit_seconds', '10', 'facebook'),
    ('rate_limit_seconds', '15', 'pinterest')
ON CONFLICT (key, platform) DO NOTHING;

COMMIT;

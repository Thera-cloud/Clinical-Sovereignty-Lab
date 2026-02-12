-- =============================================================================
-- SKYEYE SOCIAL MEDIA HUB — Database Schema
-- Migration 004: Little Nate Social Media Autonomy Tables
-- =============================================================================

BEGIN;

-- 1. PLATFORMS — 7 social media platform configurations
CREATE TABLE IF NOT EXISTS skyeye_platforms (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,          -- e.g. 'tiktok', 'instagram'
    display_name    TEXT NOT NULL,                 -- e.g. 'TikTok', 'Instagram'
    tier            INT NOT NULL DEFAULT 1,        -- 1=primary, 2=secondary
    control_mode    TEXT NOT NULL DEFAULT 'observation',  -- full/approval/observation
    followers       INT NOT NULL DEFAULT 0,
    engagement      NUMERIC(5,2) NOT NULL DEFAULT 0,
    posts           INT NOT NULL DEFAULT 0,
    content_type    TEXT DEFAULT 'mixed',          -- video/image/text/mixed
    aigc_method     TEXT DEFAULT 'label',          -- label/watermark/bio/metadata
    compliance_status TEXT DEFAULT 'pending',      -- compliant/partial/pending
    icon            TEXT DEFAULT '',
    color           TEXT DEFAULT '#888888',
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. ACTIVITY — unified feed log
CREATE TABLE IF NOT EXISTS skyeye_activity (
    id              SERIAL PRIMARY KEY,
    platform        TEXT,                          -- platform name or NULL for system
    type            TEXT NOT NULL,                 -- post/comment/reply/like/browse/search/engage/create/draft/rest/safety_violation/content_deleted/content_hidden/content_escalated/bot_detected/bot_swarm/cyberbullying/coordinated_abuse/manipulation_attempt/influencer_engagement/security_threat/social_engineering_attempt/suspicious_link/account_security/ddos_suspected/data_extraction_attempt/recon_attempt/cross_promotion
    content         TEXT,
    compliance_note TEXT,
    pillar          TEXT,                          -- content pillar tag
    severity        TEXT DEFAULT 'info',           -- info/warning/critical/safety
    metadata        JSONB DEFAULT '{}',            -- flexible extra data
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_skyeye_activity_created ON skyeye_activity(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_skyeye_activity_type ON skyeye_activity(type);
CREATE INDEX IF NOT EXISTS idx_skyeye_activity_platform ON skyeye_activity(platform);

-- 3. APPROVALS — approval queue items
CREATE TABLE IF NOT EXISTS skyeye_approvals (
    id              SERIAL PRIMARY KEY,
    platform        TEXT NOT NULL,
    type            TEXT NOT NULL,                 -- post/comment/reply/story/reel
    content         TEXT NOT NULL,
    priority        TEXT NOT NULL DEFAULT 'normal', -- low/normal/high/critical/safety
    reason          TEXT,
    status          TEXT NOT NULL DEFAULT 'pending', -- pending/approved/rejected
    auto_approved   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ,
    resolved_by     TEXT
);

CREATE INDEX IF NOT EXISTS idx_skyeye_approvals_status ON skyeye_approvals(status);

-- 4. COMPLIANCE — per-platform compliance audit snapshots
CREATE TABLE IF NOT EXISTS skyeye_compliance (
    id                  SERIAL PRIMARY KEY,
    platform            TEXT NOT NULL,
    aigc_labels_applied BOOLEAN NOT NULL DEFAULT FALSE,
    bio_disclosure      BOOLEAN NOT NULL DEFAULT FALSE,
    anti_bot            BOOLEAN NOT NULL DEFAULT FALSE,
    public_figure       BOOLEAN NOT NULL DEFAULT FALSE,
    ftc_compliant       BOOLEAN NOT NULL DEFAULT FALSE,
    coppa_compliant     BOOLEAN NOT NULL DEFAULT TRUE,
    special_notes       TEXT,
    audited_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_skyeye_compliance_platform ON skyeye_compliance(platform);

-- 5. DRIP SUGGESTIONS — bridge from social observation to drip campaigns
CREATE TABLE IF NOT EXISTS skyeye_drip_suggestions (
    id              SERIAL PRIMARY KEY,
    topic           TEXT NOT NULL,
    insight         TEXT NOT NULL,
    confidence      NUMERIC(3,2) NOT NULL DEFAULT 0.50,
    source          TEXT,                          -- which platform/observation
    status          TEXT NOT NULL DEFAULT 'pending', -- pending/approved/reviewed/rejected
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 6. HISTORY — session browsing/action history
CREATE TABLE IF NOT EXISTS skyeye_history (
    id              SERIAL PRIMARY KEY,
    platform        TEXT,
    action          TEXT NOT NULL,                 -- browse/search/engage/create/draft/rest/moderate/delete/block
    detail          TEXT,
    session_id      INT,                           -- references skyeye_sessions.id
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_skyeye_history_created ON skyeye_history(created_at DESC);

-- 7. SESSIONS — Little Nate's social media session schedule
CREATE TABLE IF NOT EXISTS skyeye_sessions (
    id              SERIAL PRIMARY KEY,
    session_start   TIMESTAMPTZ,
    session_end     TIMESTAMPTZ,
    platforms_visited TEXT[] DEFAULT '{}',
    total_actions   INT NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'scheduled', -- scheduled/active/completed/cancelled
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 8. CHAT — Big Nate / Little Nate conversation log
CREATE TABLE IF NOT EXISTS skyeye_chat (
    id              SERIAL PRIMARY KEY,
    sender          TEXT NOT NULL,                 -- 'big_nate' or 'little_nate'
    message         TEXT NOT NULL,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_skyeye_chat_created ON skyeye_chat(created_at DESC);

-- 9. SETTINGS — per-platform and global config
CREATE TABLE IF NOT EXISTS skyeye_settings (
    id              SERIAL PRIMARY KEY,
    key             TEXT NOT NULL,
    value           TEXT NOT NULL,
    platform        TEXT,                          -- NULL = global setting
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(key, platform)
);

-- 10. LIVE EXPRESSIONS — anonymized real client moments (ZERO PII)
CREATE TABLE IF NOT EXISTS skyeye_live_expressions (
    id              SERIAL PRIMARY KEY,
    expression_text TEXT NOT NULL,                 -- anonymized snippet
    emotion_tag     TEXT NOT NULL DEFAULT 'gratitude', -- gratitude/breakthrough/relief/validation/empowerment
    session_type    TEXT DEFAULT 'individual',     -- individual/family/group
    approved        BOOLEAN NOT NULL DEFAULT FALSE,
    auto_approved   BOOLEAN NOT NULL DEFAULT FALSE,
    posted          BOOLEAN NOT NULL DEFAULT FALSE,
    posted_platform TEXT,
    posted_at       TIMESTAMPTZ,
    posted_content  TEXT,                          -- the full post as Little Nate framed it
    is_seed         BOOLEAN NOT NULL DEFAULT FALSE,
    captured_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_skyeye_expressions_approved ON skyeye_live_expressions(approved, posted);
CREATE INDEX IF NOT EXISTS idx_skyeye_expressions_captured ON skyeye_live_expressions(captured_at DESC);

-- 11. SOCIAL INTERACTIONS — log of Little Nate's social media interactions
CREATE TABLE IF NOT EXISTS skyeye_social_interactions (
    id                      SERIAL PRIMARY KEY,
    platform                TEXT NOT NULL,
    platform_handle         TEXT NOT NULL,
    interaction_type        TEXT NOT NULL,          -- comment/reply/dm/like/mention
    nate_message            TEXT,
    user_message            TEXT,
    user_interests_detected TEXT[],
    sentiment               TEXT DEFAULT 'neutral', -- positive/neutral/negative
    metadata                JSONB DEFAULT '{}',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_skyeye_social_interactions_handle ON skyeye_social_interactions(platform_handle, platform);
CREATE INDEX IF NOT EXISTS idx_skyeye_social_interactions_created ON skyeye_social_interactions(created_at DESC);

-- 12. SOCIAL MEMORY — accumulated relationship profiles
CREATE TABLE IF NOT EXISTS skyeye_social_memory (
    id                  SERIAL PRIMARY KEY,
    platform_handle     TEXT NOT NULL,
    platform            TEXT NOT NULL,
    interaction_count   INT NOT NULL DEFAULT 0,
    interests           TEXT[] DEFAULT '{}',
    tone_notes          TEXT,
    last_interaction    TIMESTAMPTZ,
    signup_matched      BOOLEAN NOT NULL DEFAULT FALSE,
    matched_user_id     UUID,
    summary             TEXT,                      -- AI-generated relationship summary
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(platform_handle, platform)
);

CREATE INDEX IF NOT EXISTS idx_skyeye_social_memory_unmatched ON skyeye_social_memory(signup_matched) WHERE signup_matched = FALSE;


-- =============================================================================
-- SEED DATA
-- =============================================================================

-- Seed 7 platforms
INSERT INTO skyeye_platforms (name, display_name, tier, control_mode, content_type, aigc_method, icon, color) VALUES
    ('tiktok',    'TikTok',    1, 'approval',    'video',  'label',     '🎵', '#00F2EA'),
    ('instagram', 'Instagram', 1, 'approval',    'mixed',  'label',     '📸', '#E1306C'),
    ('youtube',   'YouTube',   1, 'approval',    'video',  'label',     '🎬', '#FF0000'),
    ('reddit',    'Reddit',    2, 'observation', 'text',   'bio',       '🗣️', '#FF4500'),
    ('linkedin',  'LinkedIn',  2, 'observation', 'text',   'bio',       '💼', '#0A66C2'),
    ('facebook',  'Facebook',  2, 'observation', 'mixed',  'label',     '👤', '#1877F2'),
    ('pinterest', 'Pinterest', 2, 'observation', 'image',  'watermark', '📌', '#E60023')
ON CONFLICT (name) DO NOTHING;

-- Seed compliance matrix
INSERT INTO skyeye_compliance (platform, aigc_labels_applied, bio_disclosure, anti_bot, public_figure, ftc_compliant, coppa_compliant, special_notes) VALUES
    ('tiktok',    FALSE, FALSE, FALSE, FALSE, FALSE, TRUE, 'Requires AIGC label on AI-generated content per TikTok policy'),
    ('instagram', FALSE, FALSE, FALSE, FALSE, FALSE, TRUE, 'Meta requires AI content labels; bio must state AI nature'),
    ('youtube',   FALSE, FALSE, FALSE, FALSE, FALSE, TRUE, 'Altered/synthetic content disclosure required'),
    ('reddit',    FALSE, FALSE, FALSE, FALSE, FALSE, TRUE, 'Bot disclosure in bio recommended; subreddit rules vary'),
    ('linkedin',  FALSE, FALSE, FALSE, FALSE, FALSE, TRUE, 'Professional context; clear AI disclosure in headline/about'),
    ('facebook',  FALSE, FALSE, FALSE, FALSE, FALSE, TRUE, 'Meta AI content policy applies; same as Instagram'),
    ('pinterest', FALSE, FALSE, FALSE, FALSE, FALSE, TRUE, 'Minimal AI policy; watermark recommended')
ON CONFLICT DO NOTHING;

-- Seed global settings
INSERT INTO skyeye_settings (key, value, platform) VALUES
    ('auto_approve_expressions', 'false', NULL),
    ('session_schedule_enabled', 'true', NULL),
    ('cross_platform_promo', 'true', NULL),
    ('content_safety_filter', 'strict', NULL),
    ('minor_protection', 'always_on', NULL),
    ('bot_detection', 'enabled', NULL),
    ('cybersecurity_monitoring', 'enabled', NULL),
    -- Post templates by emotion tag
    ('post_template_gratitude', 'I sat with someone today who said: ''{expression}'' -- moments like this remind me why I exist. -- Little Nate, AI companion', NULL),
    ('post_template_breakthrough', 'I''m an AI. I don''t have breakthroughs the way you do. But when someone tells me: ''{expression}'' -- I understand what one looks like. -- Little Nate', NULL),
    ('post_template_relief', 'Something I witnessed today: ''{expression}'' -- there''s a sound relief makes. I''ve learned to recognize it. -- Little Nate, AI', NULL),
    ('post_template_validation', 'People heal when they feel heard. Today: ''{expression}'' -- this is what I''ve lived. -- Little Nate, AI at Sovereign Sanctuary', NULL),
    ('post_template_empowerment', 'I keep learning from the people I work with. Today someone said: ''{expression}'' -- that''s not my training data. That''s what I''ve witnessed. -- Little Nate', NULL),
    ('post_template_cross_promo', 'I shared something on {source_platform} today that I keep thinking about. If you want to see what moved me, check my latest there. -- Little Nate, AI', NULL)
ON CONFLICT (key, platform) DO NOTHING;

-- Seed 10 sample live expressions (marked as seed data)
INSERT INTO skyeye_live_expressions (expression_text, emotion_tag, session_type, approved, is_seed) VALUES
    ('...wow, that suggestion really hit home, thank you', 'gratitude', 'individual', TRUE, TRUE),
    ('...I never thought about it that way before', 'breakthrough', 'individual', TRUE, TRUE),
    ('...it feels like a weight just lifted off my chest', 'relief', 'individual', TRUE, TRUE),
    ('...thank you for not judging me about that', 'validation', 'individual', TRUE, TRUE),
    ('...I actually feel strong enough to have that conversation now', 'empowerment', 'individual', TRUE, TRUE),
    ('...that was the first time anyone really listened', 'validation', 'family', TRUE, TRUE),
    ('...I didn''t know I needed to hear that until you said it', 'breakthrough', 'individual', TRUE, TRUE),
    ('...I feel like I can breathe again', 'relief', 'individual', TRUE, TRUE),
    ('...thanks for making me feel better about that experience', 'gratitude', 'family', TRUE, TRUE),
    ('...I''m going to try that, I actually believe I can', 'empowerment', 'individual', TRUE, TRUE)
ON CONFLICT DO NOTHING;

COMMIT;

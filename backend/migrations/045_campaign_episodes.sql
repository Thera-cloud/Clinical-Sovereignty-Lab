-- =============================================================================
-- Migration 045: Campaign Episode System
-- Storytelling campaigns, episode sequencing, A/B testing, engagement
-- thresholds, cross-platform threading, drip touchpoints, and templates.
-- =============================================================================

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. campaign_templates — Pre-built narrative structures
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS campaign_templates (
    id                  SERIAL PRIMARY KEY,
    name                TEXT NOT NULL UNIQUE,
    description         TEXT,
    episode_structure   JSONB NOT NULL DEFAULT '[]',
    default_platforms   TEXT[] DEFAULT ARRAY['linkedin','reddit','tiktok','instagram'],
    default_episode_count INT DEFAULT 5,
    default_interval_hours INT DEFAULT 24,
    narrative_prompts   JSONB NOT NULL DEFAULT '{}',
    built_in            BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Seed 5 built-in templates
INSERT INTO campaign_templates (name, description, default_episode_count, default_interval_hours, episode_structure, narrative_prompts)
VALUES
(
    'romance_arc',
    'Multi-episode romantic narrative with cliff-hangers and audience participation. Audience votes influence the story direction.',
    6, 24,
    '[
        {"episode": 1, "title": "The Meeting", "purpose": "introduce characters, set emotional tone, end with a hook"},
        {"episode": 2, "title": "The Connection", "purpose": "deepen relationship, reveal vulnerability, cliff-hanger"},
        {"episode": 3, "title": "The Conflict", "purpose": "introduce obstacle, audience chooses direction"},
        {"episode": 4, "title": "The Separation", "purpose": "emotional low point, cliff-hanger about reunion"},
        {"episode": 5, "title": "The Revelation", "purpose": "twist based on audience feedback, legacy content tie-in"},
        {"episode": 6, "title": "The Resolution", "purpose": "emotional climax, call to action, invite to platform"}
    ]'::jsonb,
    '{
        "episode_prompt_template": "You are writing Episode {{episode_number}} of a {{total_episodes}}-part interactive romance story for social media. Title: {{episode_title}}. Purpose: {{episode_purpose}}. Previous episode summary: {{previous_episode}}. Audience feedback from last episode: {{audience_feedback}}. Emotional themes from real sessions (anonymized): {{me2me_themes}}. Write a compelling, emotionally authentic post that ends with a cliff-hanger or question for the audience. The story should feel real, raw, and relatable.",
        "ab_variant_prompt": "Generate two different opening hooks for this episode. Variant A: Lead with raw emotion. Variant B: Lead with curiosity/mystery. Both should hook the reader in the first line."
    }'::jsonb
),
(
    'heros_journey',
    'Personal growth narrative following the classic hero''s journey arc: departure, trials, transformation, return.',
    5, 48,
    '[
        {"episode": 1, "title": "The Call", "purpose": "ordinary world disrupted, call to adventure"},
        {"episode": 2, "title": "The Threshold", "purpose": "crossing into the unknown, meeting mentors"},
        {"episode": 3, "title": "The Trials", "purpose": "facing challenges, deepest fear, audience encouragement"},
        {"episode": 4, "title": "The Transformation", "purpose": "breakthrough moment, new understanding"},
        {"episode": 5, "title": "The Return", "purpose": "bringing wisdom home, invitation to community"}
    ]'::jsonb,
    '{
        "episode_prompt_template": "You are writing Episode {{episode_number}} of a {{total_episodes}}-part personal growth story. Title: {{episode_title}}. Purpose: {{episode_purpose}}. Previous: {{previous_episode}}. Audience reactions: {{audience_feedback}}. Real emotional themes: {{me2me_themes}}. Write an authentic, inspiring post about transformation.",
        "ab_variant_prompt": "Generate two hooks: Variant A: Start with a moment of struggle. Variant B: Start with a moment of surprising strength."
    }'::jsonb
),
(
    'community_challenge',
    'Audience participation campaign with tasks, leaderboard energy, and recap posts.',
    4, 72,
    '[
        {"episode": 1, "title": "The Challenge", "purpose": "announce the challenge, explain rules, inspire participation"},
        {"episode": 2, "title": "The Momentum", "purpose": "share early results, highlight participants, raise stakes"},
        {"episode": 3, "title": "The Push", "purpose": "hardest part, encouragement, audience shares progress"},
        {"episode": 4, "title": "The Celebration", "purpose": "results, highlights, community gratitude, next steps"}
    ]'::jsonb,
    '{
        "episode_prompt_template": "You are writing Episode {{episode_number}} of a {{total_episodes}}-part community challenge. Title: {{episode_title}}. Purpose: {{episode_purpose}}. Previous: {{previous_episode}}. Participant feedback: {{audience_feedback}}. Write an energizing, community-focused post.",
        "ab_variant_prompt": "Generate two hooks: Variant A: Start with a bold challenge statement. Variant B: Start with a participant success story."
    }'::jsonb
),
(
    'educational_series',
    'Deep-dive topic exploration with discussion prompts and progressive learning.',
    6, 48,
    '[
        {"episode": 1, "title": "The Question", "purpose": "pose the central question, invite curiosity"},
        {"episode": 2, "title": "The Foundation", "purpose": "core concepts, relatable examples"},
        {"episode": 3, "title": "The Depth", "purpose": "deeper exploration, counter-intuitive insights"},
        {"episode": 4, "title": "The Practice", "purpose": "actionable exercise, audience tries it"},
        {"episode": 5, "title": "The Discussion", "purpose": "audience shares experiences, synthesize"},
        {"episode": 6, "title": "The Integration", "purpose": "key takeaways, resources, community invite"}
    ]'::jsonb,
    '{
        "episode_prompt_template": "You are writing Episode {{episode_number}} of a {{total_episodes}}-part educational series. Title: {{episode_title}}. Purpose: {{episode_purpose}}. Previous: {{previous_episode}}. Discussion from audience: {{audience_feedback}}. Emotional context: {{me2me_themes}}. Write an insightful, accessible post that makes people think.",
        "ab_variant_prompt": "Generate two hooks: Variant A: Start with a surprising statistic or fact. Variant B: Start with a personal anecdote."
    }'::jsonb
),
(
    'testimonial_showcase',
    'Anonymized client moments woven into a compelling multi-part narrative.',
    4, 72,
    '[
        {"episode": 1, "title": "The Moment", "purpose": "one powerful anonymized moment, set the tone"},
        {"episode": 2, "title": "The Pattern", "purpose": "connect multiple moments, show a theme"},
        {"episode": 3, "title": "The Breakthrough", "purpose": "transformation story, emotional peak"},
        {"episode": 4, "title": "The Invitation", "purpose": "what this means for the audience, CTA"}
    ]'::jsonb,
    '{
        "episode_prompt_template": "You are writing Episode {{episode_number}} of a {{total_episodes}}-part testimonial showcase. Title: {{episode_title}}. Purpose: {{episode_purpose}}. Previous: {{previous_episode}}. Audience reactions: {{audience_feedback}}. Anonymized real themes: {{me2me_themes}}. Write a moving, authentic post grounded in real emotional truth. NEVER reveal identifying details.",
        "ab_variant_prompt": "Generate two hooks: Variant A: Start in the middle of the emotional moment. Variant B: Start with the aftermath and work backwards."
    }'::jsonb
)
ON CONFLICT (name) DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. storytelling_campaigns — Campaign instances
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS storytelling_campaigns (
    id                      SERIAL PRIMARY KEY,
    title                   TEXT NOT NULL,
    narrative_premise       TEXT,
    campaign_type           TEXT DEFAULT 'standard',
    template_name           TEXT REFERENCES campaign_templates(name),
    platforms               TEXT[] DEFAULT ARRAY['linkedin','reddit','tiktok','instagram'],
    total_episodes          INT DEFAULT 1,
    current_episode         INT DEFAULT 0,
    episode_interval_hours  INT DEFAULT 24,

    -- Audience feedback
    audience_feedback_enabled BOOLEAN DEFAULT TRUE,
    audience_feedback       JSONB DEFAULT '[]',

    -- Engagement thresholds
    min_engagement_threshold    INT DEFAULT 0,
    extend_engagement_threshold INT DEFAULT 0,

    -- A/B testing
    ab_test_enabled         BOOLEAN DEFAULT FALSE,
    ab_test_config          JSONB DEFAULT '{}',

    -- Drip integration
    drip_touchpoints        JSONB DEFAULT '[]',

    -- Status
    status                  TEXT DEFAULT 'designing',
    marketing_action_id     INT,

    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_campaigns_status ON storytelling_campaigns(status);
CREATE INDEX IF NOT EXISTS idx_campaigns_action ON storytelling_campaigns(marketing_action_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. Extend skyeye_content_queue with campaign fields
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE skyeye_content_queue
    ADD COLUMN IF NOT EXISTS campaign_id       INT REFERENCES storytelling_campaigns(id),
    ADD COLUMN IF NOT EXISTS episode_number    INT,
    ADD COLUMN IF NOT EXISTS sequence_order    INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS depends_on_post_id INT,
    ADD COLUMN IF NOT EXISTS cross_thread_refs JSONB DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS ab_variant       TEXT,
    ADD COLUMN IF NOT EXISTS video_script     JSONB;

CREATE INDEX IF NOT EXISTS idx_queue_campaign ON skyeye_content_queue(campaign_id) WHERE campaign_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_queue_episode ON skyeye_content_queue(campaign_id, episode_number) WHERE campaign_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_queue_depends ON skyeye_content_queue(depends_on_post_id) WHERE depends_on_post_id IS NOT NULL;

COMMIT;

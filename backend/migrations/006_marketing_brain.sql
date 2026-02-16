-- ============================================================================
-- 006_marketing_brain.sql
-- Marketing Brain Architecture: strategy engine, funnel routing, command
-- protocol, A/B testing, and growth snapshots.
-- ============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Marketing Playbook (single-row strategy context, versioned)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS marketing_playbook (
    id              SERIAL PRIMARY KEY,
    content_pillars JSONB NOT NULL DEFAULT '[]'::jsonb,
    target_audiences JSONB NOT NULL DEFAULT '{}'::jsonb,
    conversion_funnels JSONB NOT NULL DEFAULT '{}'::jsonb,
    performance_benchmarks JSONB NOT NULL DEFAULT '{}'::jsonb,
    competitive_notes JSONB NOT NULL DEFAULT '[]'::jsonb,
    active_campaigns JSONB NOT NULL DEFAULT '[]'::jsonb,
    regional_focus  JSONB NOT NULL DEFAULT '{}'::jsonb,
    collaboration_targets JSONB NOT NULL DEFAULT '[]'::jsonb,
    content_mix     JSONB NOT NULL DEFAULT '{}'::jsonb,
    posting_schedule JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_strategy_review TIMESTAMPTZ,
    version         INT NOT NULL DEFAULT 1,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed the initial playbook row
INSERT INTO marketing_playbook (
    content_pillars,
    target_audiences,
    conversion_funnels,
    content_mix,
    posting_schedule
) VALUES (
    '[
        {"name": "emotional_coherence", "description": "CEE scores, emotional growth, Nevedal formula insights", "weight": 0.30, "avg_engagement": 0},
        {"name": "daily_wins", "description": "Small victories, habit building, resilience moments", "weight": 0.25, "avg_engagement": 0},
        {"name": "breathing_and_mindfulness", "description": "Practical techniques, grounding exercises", "weight": 0.15, "avg_engagement": 0},
        {"name": "therapy_demystified", "description": "Making therapy accessible, reducing stigma", "weight": 0.15, "avg_engagement": 0},
        {"name": "family_connection", "description": "Family dynamics, parenting, connected care", "weight": 0.10, "avg_engagement": 0},
        {"name": "coach_spotlight", "description": "Professional development, coaching excellence", "weight": 0.05, "avg_engagement": 0}
    ]'::jsonb,
    '{
        "tiktok":    {"primary": "young_adults_anxiety", "secondary": "wellness_seekers", "age_range": "18-35"},
        "instagram": {"primary": "wellness_community", "secondary": "parents", "age_range": "25-45"},
        "youtube":   {"primary": "therapy_curious", "secondary": "mental_health_educators", "age_range": "20-50"},
        "reddit":    {"primary": "anxiety_support", "secondary": "therapy_seekers", "age_range": "18-40"},
        "linkedin":  {"primary": "therapists_coaches", "secondary": "healthcare_professionals", "age_range": "28-55"},
        "facebook":  {"primary": "parents_families", "secondary": "support_groups", "age_range": "30-55"},
        "pinterest": {"primary": "self_care_planners", "secondary": "wellness_visual", "age_range": "25-45"}
    }'::jsonb,
    '{
        "individual": {
            "stages": ["social_engage", "quiz_start", "quiz_complete", "golden_ticket", "signup", "active_client"],
            "default_quiz": "the_mirror",
            "drip_campaign": "default_journey"
        },
        "coach": {
            "stages": ["linkedin_connect", "content_engage", "demo_view", "quiz_start", "application", "onboarded"],
            "default_quiz": "the_healers_mirror",
            "drip_campaign": "coach_recruitment"
        },
        "family": {
            "stages": ["social_engage", "family_quiz", "family_ticket", "family_signup"],
            "default_quiz": "family_compass",
            "drip_campaign": "family_journey"
        }
    }'::jsonb,
    '{
        "tiktok":    {"emotional_coherence": 0.40, "daily_wins": 0.30, "breathing": 0.20, "therapy": 0.10},
        "instagram": {"daily_wins": 0.30, "breathing": 0.25, "family": 0.25, "emotional_coherence": 0.20},
        "youtube":   {"therapy": 0.35, "emotional_coherence": 0.30, "breathing": 0.20, "daily_wins": 0.15},
        "reddit":    {"therapy": 0.40, "emotional_coherence": 0.30, "daily_wins": 0.20, "breathing": 0.10},
        "linkedin":  {"coach_spotlight": 0.40, "therapy": 0.30, "emotional_coherence": 0.20, "daily_wins": 0.10},
        "facebook":  {"family": 0.35, "daily_wins": 0.25, "breathing": 0.20, "therapy": 0.20},
        "pinterest": {"breathing": 0.35, "daily_wins": 0.30, "family": 0.20, "emotional_coherence": 0.15}
    }'::jsonb,
    '{
        "tiktok":    {"sessions_per_day": 3, "best_hours_utc": [14, 18, 22]},
        "instagram": {"sessions_per_day": 2, "best_hours_utc": [13, 19]},
        "youtube":   {"sessions_per_day": 1, "best_hours_utc": [16]},
        "reddit":    {"sessions_per_day": 2, "best_hours_utc": [15, 21]},
        "linkedin":  {"sessions_per_day": 1, "best_hours_utc": [14]},
        "facebook":  {"sessions_per_day": 1, "best_hours_utc": [17]},
        "pinterest": {"sessions_per_day": 1, "best_hours_utc": [15]}
    }'::jsonb
) ON CONFLICT DO NOTHING;


-- ---------------------------------------------------------------------------
-- 2. Funnel Routing Log (social-to-quiz conversion tracking)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS funnel_routing_log (
    id              SERIAL PRIMARY KEY,
    social_handle   TEXT NOT NULL,
    platform        TEXT NOT NULL,
    engagement_score FLOAT NOT NULL DEFAULT 0,
    interaction_count INT NOT NULL DEFAULT 0,
    audience_type   TEXT NOT NULL DEFAULT 'individual',  -- individual, coach, family
    assigned_funnel TEXT,
    assigned_quiz_id UUID REFERENCES quizzes(id),
    quiz_url        TEXT,
    cta_type        TEXT,             -- bio_link, dm, story, post_cta
    cta_sent_at     TIMESTAMPTZ,
    quiz_started_at TIMESTAMPTZ,
    quiz_completed_at TIMESTAMPTZ,
    golden_ticket_issued_at TIMESTAMPTZ,
    converted_at    TIMESTAMPTZ,
    prospect_id     UUID REFERENCES prospects(id),
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_funnel_routing_handle
    ON funnel_routing_log (social_handle, platform);
CREATE INDEX IF NOT EXISTS idx_funnel_routing_stage
    ON funnel_routing_log (assigned_funnel, converted_at);


-- ---------------------------------------------------------------------------
-- 3. Marketing Actions (command protocol action log)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS marketing_actions (
    id              SERIAL PRIMARY KEY,
    proposed_by     TEXT NOT NULL DEFAULT 'little_nate',  -- little_nate | big_nate
    action_type     TEXT NOT NULL,     -- launch_campaign, create_quiz, shift_content_mix,
                                        -- collaboration_outreach, pause_platform, create_drip,
                                        -- adjust_schedule, kill_campaign, a]b_test
    title           TEXT NOT NULL,
    description     TEXT,
    parameters      JSONB NOT NULL DEFAULT '{}'::jsonb,
    status          TEXT NOT NULL DEFAULT 'proposed',  -- proposed, approved, executing, completed, rejected, deferred
    priority        TEXT NOT NULL DEFAULT 'normal',    -- urgent, high, normal, low
    proposed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_at     TIMESTAMPTZ,
    approved_by     TEXT,              -- big_nate | auto
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    result          JSONB,
    rejection_reason TEXT,
    chat_message_id INT,               -- reference to skyeye_chat message that proposed/approved
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_marketing_actions_status
    ON marketing_actions (status, priority);


-- ---------------------------------------------------------------------------
-- 4. Content A/B Tests
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS content_ab_tests (
    id              SERIAL PRIMARY KEY,
    test_name       TEXT NOT NULL,
    test_type       TEXT NOT NULL DEFAULT 'cta',  -- cta, content, quiz, subject_line
    platform        TEXT,
    variant_a       JSONB NOT NULL,
    variant_b       JSONB NOT NULL,
    variant_a_impressions INT NOT NULL DEFAULT 0,
    variant_a_clicks     INT NOT NULL DEFAULT 0,
    variant_a_conversions INT NOT NULL DEFAULT 0,
    variant_b_impressions INT NOT NULL DEFAULT 0,
    variant_b_clicks     INT NOT NULL DEFAULT 0,
    variant_b_conversions INT NOT NULL DEFAULT 0,
    winner          TEXT,              -- a | b | inconclusive
    confidence      FLOAT,
    status          TEXT NOT NULL DEFAULT 'running',  -- running, completed, cancelled
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ---------------------------------------------------------------------------
-- 5. Growth Snapshots (daily/weekly metrics for trend analysis)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS growth_snapshots (
    id              SERIAL PRIMARY KEY,
    snapshot_date   DATE NOT NULL,
    snapshot_type   TEXT NOT NULL DEFAULT 'daily',  -- daily, weekly, monthly
    platform_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- e.g. {"tiktok": {"followers": 150, "engagement_rate": 0.08, "posts": 3, ...}, ...}
    funnel_metrics  JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- e.g. {"social_impressions": 5000, "cta_clicks": 120, "quiz_starts": 45, "quiz_completes": 30, ...}
    campaign_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- e.g. {"emails_sent": 200, "open_rate": 0.42, "click_rate": 0.15, "conversions": 8}
    regional_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- e.g. {"US": {"signups": 12, "active": 45}, "UK": {"signups": 3, "active": 8}}
    total_prospects INT NOT NULL DEFAULT 0,
    total_clients   INT NOT NULL DEFAULT 0,
    total_coaches   INT NOT NULL DEFAULT 0,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(snapshot_date, snapshot_type)
);

CREATE INDEX IF NOT EXISTS idx_growth_snapshots_date
    ON growth_snapshots (snapshot_date DESC, snapshot_type);


-- ---------------------------------------------------------------------------
-- 6. Extend skyeye_social_memory with funnel tracking columns
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'skyeye_social_memory' AND column_name = 'funnel_stage') THEN
        ALTER TABLE skyeye_social_memory ADD COLUMN funnel_stage TEXT DEFAULT 'unqualified';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'skyeye_social_memory' AND column_name = 'assigned_quiz_id') THEN
        ALTER TABLE skyeye_social_memory ADD COLUMN assigned_quiz_id UUID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'skyeye_social_memory' AND column_name = 'cta_last_sent') THEN
        ALTER TABLE skyeye_social_memory ADD COLUMN cta_last_sent TIMESTAMPTZ;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'skyeye_social_memory' AND column_name = 'conversion_score') THEN
        ALTER TABLE skyeye_social_memory ADD COLUMN conversion_score FLOAT DEFAULT 0;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'skyeye_social_memory' AND column_name = 'audience_type') THEN
        ALTER TABLE skyeye_social_memory ADD COLUMN audience_type TEXT DEFAULT 'individual';
    END IF;
END $$;


-- ---------------------------------------------------------------------------
-- 7. Extend skyeye_content_queue with CTA and A/B test columns
-- NOTE: skyeye_content_queue is created in migration 010. If running migrations
-- in order on a fresh DB, this block will be skipped and the columns should be
-- added after 010 applies. The IF EXISTS guard prevents failures.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    -- Only proceed if the table exists (created by migration 010)
    IF EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_name = 'skyeye_content_queue') THEN
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name = 'skyeye_content_queue' AND column_name = 'cta_type') THEN
            ALTER TABLE skyeye_content_queue ADD COLUMN cta_type TEXT;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name = 'skyeye_content_queue' AND column_name = 'cta_target_url') THEN
            ALTER TABLE skyeye_content_queue ADD COLUMN cta_target_url TEXT;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name = 'skyeye_content_queue' AND column_name = 'ab_test_id') THEN
            ALTER TABLE skyeye_content_queue ADD COLUMN ab_test_id INT REFERENCES content_ab_tests(id);
        END IF;
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name = 'skyeye_content_queue' AND column_name = 'content_pillar') THEN
            ALTER TABLE skyeye_content_queue ADD COLUMN content_pillar TEXT;
        END IF;
    END IF;
END $$;

COMMIT;

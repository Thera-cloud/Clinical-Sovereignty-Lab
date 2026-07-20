-- QUANTUM-CRYSTAL-ARCH — Newsletter Growth Engine
-- Trend candidates, referral attribution, seasonal topic seed

ALTER TABLE newsletter_subscribers
    ADD COLUMN IF NOT EXISTS ref_slug TEXT;

CREATE TABLE IF NOT EXISTS newsletter_trend_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    headline TEXT NOT NULL,
    category TEXT NOT NULL
        CHECK (category IN (
            'politics', 'music', 'fitness', 'influencer', 'culture',
            'tech', 'arts', 'military', 'neurodivergence', 'general'
        )),
    source TEXT,
    source_url TEXT,
    velocity REAL NOT NULL DEFAULT 0.5,
    paired_topic_key TEXT,
    paired_title TEXT,
    paired_at TIMESTAMPTZ,
    harvested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_newsletter_trend_harvested
    ON newsletter_trend_candidates (harvested_at DESC);
CREATE INDEX IF NOT EXISTS idx_newsletter_trend_velocity
    ON newsletter_trend_candidates (velocity DESC, harvested_at DESC)
    WHERE paired_at IS NULL;

-- Seasonal / evergreen seed into forecast (idempotent by topic_key + label)
INSERT INTO newsletter_topic_forecast
    (topic_key, seasonal_label, target_week, news_velocity, foresight_score, metadata)
SELECT v.topic_key, v.seasonal_label, CURRENT_DATE + (v.offset_days || ' days')::interval,
       0, v.foresight_score, jsonb_build_object('domain', v.domain, 'seed', true)
FROM (VALUES
    ('neurodiversity_celebration', 'Neurodiversity Celebration Week', 'neurodivergence', 0.72, 60),
    ('autism_acceptance', 'Autism Acceptance Month', 'neurodivergence', 0.75, 90),
    ('adhd_awareness', 'ADHD Awareness Month', 'neurodivergence', 0.74, 270),
    ('mental_health_awareness', 'Mental Health Awareness Month', 'general', 0.78, 120),
    ('back_to_school_anxiety', 'Back to school', 'relationships', 0.70, 220),
    ('seasonal_affective', 'Seasonal affective onset', 'general', 0.68, 300),
    ('holiday_grief', 'Holiday grief and family stress', 'grief', 0.71, 340),
    ('new_year_pressure', 'New Year pressure', 'burnout', 0.69, 5),
    ('veterans_day_reintegration', 'Veterans Day', 'military', 0.76, 310),
    ('memorial_day_memory', 'Memorial Day', 'military', 0.70, 145),
    ('arts_and_healing', 'Arts and healing', 'arts', 0.65, 30),
    ('fitness_shame_free', 'Movement without shame', 'fitness', 0.64, 45),
    ('curiosity_lifelong_learning', 'Curiosity and lifelong learning', 'curiosity', 0.62, 15),
    ('self_compassion_practice', 'Self-compassion practice', 'general', 0.66, 20),
    ('military_family_stress', 'Military family stress', 'military', 0.68, 100),
    ('masking_and_unmasking', 'Masking and unmasking', 'neurodivergence', 0.67, 80),
    ('film_catharsis', 'Film as emotional mirror', 'arts', 0.63, 50),
    ('museum_slow_attention', 'Museums as slow attention', 'arts', 0.61, 55),
    ('sleep_and_regulation', 'Sleep and emotional regulation', 'general', 0.65, 35),
    ('parenting_steadiness', 'Parenting with steadiness', 'relationships', 0.66, 40),
    ('burnout_recovery', 'Burnout recovery', 'burnout', 0.70, 25),
    ('grief_after_loss', 'Grief after loss', 'grief', 0.72, 70),
    ('doomscroll_nervous_system', 'Doomscrolling and the nervous system', 'general', 0.73, 10),
    ('supporting_neurodivergent_loved_one', 'Supporting a neurodivergent loved one', 'neurodivergence', 0.71, 85),
    ('war_headlines_without_shutdown', 'War headlines without shutting down', 'military', 0.74, 12),
    ('theater_and_empathy', 'Theater and empathy', 'arts', 0.60, 95)
) AS v(topic_key, seasonal_label, domain, foresight_score, offset_days)
WHERE NOT EXISTS (
    SELECT 1 FROM newsletter_topic_forecast f
    WHERE f.topic_key = v.topic_key
      AND f.seasonal_label = v.seasonal_label
      AND f.metadata->>'seed' = 'true'
);

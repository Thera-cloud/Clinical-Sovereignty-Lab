-- ============================================================================
-- Migration 011: Prospect-to-User Data Linking (renumbered from 006)
-- Adds user_id columns to prospect tables so quiz data follows
-- the prospect when they convert to a client via Golden Ticket.
-- ============================================================================

-- Add user_id to nate_insights (so insights are accessible by user_id after conversion)
ALTER TABLE nate_insights ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_nate_insights_user_id ON nate_insights(user_id);

-- Add user_id to quiz_responses
ALTER TABLE quiz_responses ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_quiz_responses_user_id ON quiz_responses(user_id);

-- Add user_id to coaching_assessments
ALTER TABLE coaching_assessments ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_coaching_assessments_user_id ON coaching_assessments(user_id);

-- Add user_id to prospect_story_store
ALTER TABLE prospect_story_store ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_prospect_story_store_user_id ON prospect_story_store(user_id);

-- Create a VIEW for easy access: user → their full prospect journey
CREATE OR REPLACE VIEW user_prospect_journey AS
SELECT
    u.id AS user_id,
    u.username,
    u.name AS user_name,
    p.id AS prospect_id,
    p.email AS prospect_email,
    p.converted_at,
    ni.quiz_id,
    q.title AS quiz_title,
    q.quiz_order,
    ni.insight_text,
    ni.patterns,
    ni.strength,
    ni.growth_area,
    ni.created_at AS insight_created_at,
    ca.snapshot AS assessment_snapshot,
    ca.goals AS assessment_goals,
    ca.legacy_statement,
    pss.cumulative_narrative,
    pss.emotional_profile
FROM users u
JOIN prospects p ON p.converted_to_client_id = u.id
LEFT JOIN nate_insights ni ON ni.prospect_id = p.id
LEFT JOIN quizzes q ON q.id = ni.quiz_id
LEFT JOIN coaching_assessments ca ON ca.prospect_id = p.id
LEFT JOIN prospect_story_store pss ON pss.prospect_id = p.id
ORDER BY q.quiz_order;

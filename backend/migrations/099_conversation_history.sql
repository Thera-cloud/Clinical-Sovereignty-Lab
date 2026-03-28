-- Migration 099: conversation_history — PostgreSQL-first conversation memory
-- Replaces memory.json (1000-entry cap) with unlimited lifetime retention.
-- Includes audit seed data for audit_student_1_hw and FTS index for search.

CREATE TABLE IF NOT EXISTS conversation_history (
    id              BIGSERIAL PRIMARY KEY,
    user_id         TEXT NOT NULL,
    session_id      TEXT,
    user_text       TEXT NOT NULL,
    ai_text         TEXT NOT NULL,
    word_count_user INT DEFAULT 0,
    word_count_ai   INT DEFAULT 0,
    metadata        JSONB DEFAULT '{}',
    me2me_absorbed  BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_convhist_user    ON conversation_history(user_id);
CREATE INDEX IF NOT EXISTS idx_convhist_session ON conversation_history(session_id);
CREATE INDEX IF NOT EXISTS idx_convhist_created ON conversation_history(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_convhist_fts     ON conversation_history
    USING GIN (to_tsvector('english', user_text || ' ' || ai_text));
CREATE INDEX IF NOT EXISTS idx_convhist_me2me   ON conversation_history(user_id)
    WHERE me2me_absorbed = FALSE;

-- Audit seed data for audit_student_1_hw (migration 065 created this CLIENT account)
INSERT INTO conversation_history (user_id, session_id, user_text, ai_text, word_count_user, word_count_ai, metadata)
VALUES
    ('audit_student_1_hw', 'AUDIT_SES_001', 'How do I manage anxiety?',
     'Anxiety is a natural response to perceived threats. Let''s explore some grounding techniques that can help you stay present when anxiety arises.',
     6, 23, '{"is_audit_seed": true}'::jsonb),
    ('audit_student_1_hw', 'AUDIT_SES_001', 'What about breathing exercises?',
     'Deep breathing activates your parasympathetic nervous system. Try the 4-7-8 technique: breathe in for 4 seconds, hold for 7, exhale for 8.',
     5, 24, '{"is_audit_seed": true}'::jsonb),
    ('audit_student_1_hw', 'AUDIT_SES_002', 'I had a stressful week at work.',
     'I hear you. Work stress can accumulate and affect every area of life. What specific situations felt most overwhelming this week?',
     8, 20, '{"is_audit_seed": true}'::jsonb)
ON CONFLICT DO NOTHING;

-- Update trust baseline for me2me auditor (12 → 16 checks)
UPDATE trust_baseline
SET parameter_value = '{"expected": 16, "description": "Me2Me Legacy Pipeline — 9 REST + 3 DB + 4 Conversation History checks"}'::jsonb
WHERE parameter_key = 'me2me_check_count';

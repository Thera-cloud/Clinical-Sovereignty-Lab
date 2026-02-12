-- =============================================================================
-- LITTLE NATE — Seed: 5 Emotional Coherence Quizzes
-- Version: 1.0
-- Depends on: 002_drip_campaign.sql
-- =============================================================================

-- =============================================================================
-- QUIZ 1: Emotional Awareness (Day 1)
-- =============================================================================
INSERT INTO quizzes (id, title, description, theme, dimension, quiz_order, is_final)
VALUES (
    'a1111111-1111-1111-1111-111111111111',
    'The Mirror',
    'How well do you see yourself? This quiz explores your relationship with your own emotional landscape — how you notice, name, and navigate what you feel.',
    'Emotional Awareness',
    'self_awareness',
    1,
    FALSE
);

INSERT INTO quiz_questions (quiz_id, question_order, question_text, question_type, scale_min, scale_max, scale_min_label, scale_max_label, dimension_tag) VALUES
('a1111111-1111-1111-1111-111111111111', 1, 'When a strong emotion arises, how quickly do you recognize what you''re feeling?', 'scale', 1, 10, 'Takes me a long time', 'I notice immediately', 'recognition_speed'),
('a1111111-1111-1111-1111-111111111111', 2, 'How comfortable are you sitting with an uncomfortable emotion without trying to fix or escape it?', 'scale', 1, 10, 'Very uncomfortable', 'Completely at ease', 'distress_tolerance'),
('a1111111-1111-1111-1111-111111111111', 3, 'Which of these best describes your typical response when you feel overwhelmed?', 'multiple_choice', 1, 10, NULL, NULL, 'overwhelm_response'),
('a1111111-1111-1111-1111-111111111111', 4, 'How often do you find yourself feeling emotions that seem to belong to someone else around you?', 'scale', 1, 10, 'Never', 'Constantly', 'emotional_absorption'),
('a1111111-1111-1111-1111-111111111111', 5, 'In a single sentence, describe the emotion you feel most often but rarely talk about.', 'open_text', 1, 10, NULL, NULL, 'hidden_emotion');

-- Options for Q3
UPDATE quiz_questions SET options = '[
    {"value": "a", "label": "I shut down and go numb"},
    {"value": "b", "label": "I get anxious and try to control everything"},
    {"value": "c", "label": "I reach out to someone I trust"},
    {"value": "d", "label": "I distract myself with activity or substances"},
    {"value": "e", "label": "I let myself feel it and wait for it to pass"},
    {"value": "f", "label": "I get angry or irritable"}
]'::jsonb
WHERE quiz_id = 'a1111111-1111-1111-1111-111111111111' AND question_order = 3;

-- =============================================================================
-- QUIZ 2: Relational Patterns (Day 2)
-- =============================================================================
INSERT INTO quizzes (id, title, description, theme, dimension, quiz_order, is_final)
VALUES (
    'a2222222-2222-2222-2222-222222222222',
    'The Bridge',
    'How do you connect? This quiz explores the invisible patterns in your closest relationships — the way you reach toward others and what happens when they reach back.',
    'Relational Patterns',
    'relational_attunement',
    2,
    FALSE
);

INSERT INTO quiz_questions (quiz_id, question_order, question_text, question_type, scale_min, scale_max, scale_min_label, scale_max_label, dimension_tag) VALUES
('a2222222-2222-2222-2222-222222222222', 1, 'When someone you care about pulls away, what is your first instinct?', 'multiple_choice', 1, 10, NULL, NULL, 'attachment_response'),
('a2222222-2222-2222-2222-222222222222', 2, 'How easy is it for you to ask for help when you really need it?', 'scale', 1, 10, 'Nearly impossible', 'Very easy', 'vulnerability_comfort'),
('a2222222-2222-2222-2222-222222222222', 3, 'In conflict, I tend to...', 'multiple_choice', 1, 10, NULL, NULL, 'conflict_style'),
('a2222222-2222-2222-2222-222222222222', 4, 'How often do you feel truly seen by the people closest to you?', 'scale', 1, 10, 'Almost never', 'Almost always', 'felt_understanding'),
('a2222222-2222-2222-2222-222222222222', 5, 'Describe a moment when you felt deeply connected to another person. What made it different?', 'open_text', 1, 10, NULL, NULL, 'connection_peak');

UPDATE quiz_questions SET options = '[
    {"value": "a", "label": "I pursue them — texts, calls, trying to close the gap"},
    {"value": "b", "label": "I pull away too — if they don''t want me, fine"},
    {"value": "c", "label": "I get anxious but try to give them space"},
    {"value": "d", "label": "I analyze what went wrong obsessively"},
    {"value": "e", "label": "I stay steady and trust it will resolve"},
    {"value": "f", "label": "I reach out once, then focus on myself"}
]'::jsonb
WHERE quiz_id = 'a2222222-2222-2222-2222-222222222222' AND question_order = 1;

UPDATE quiz_questions SET options = '[
    {"value": "a", "label": "Shut down and withdraw"},
    {"value": "b", "label": "Raise my voice or get defensive"},
    {"value": "c", "label": "Over-explain or over-apologize"},
    {"value": "d", "label": "Stay calm and try to understand their side"},
    {"value": "e", "label": "Avoid the conflict entirely"},
    {"value": "f", "label": "Get tearful or overwhelmed"}
]'::jsonb
WHERE quiz_id = 'a2222222-2222-2222-2222-222222222222' AND question_order = 3;

-- =============================================================================
-- QUIZ 3: Inner Critic & Self-Compassion (Day 3)
-- =============================================================================
INSERT INTO quizzes (id, title, description, theme, dimension, quiz_order, is_final)
VALUES (
    'a3333333-3333-3333-3333-333333333333',
    'The Voice Inside',
    'What does your inner dialogue sound like? This quiz maps the territory between your harshest self-judgment and your capacity for self-compassion.',
    'Inner Critic & Self-Compassion',
    'self_regulation',
    3,
    FALSE
);

INSERT INTO quiz_questions (quiz_id, question_order, question_text, question_type, scale_min, scale_max, scale_min_label, scale_max_label, dimension_tag) VALUES
('a3333333-3333-3333-3333-333333333333', 1, 'When you make a mistake, what does your inner voice sound like?', 'multiple_choice', 1, 10, NULL, NULL, 'inner_critic_tone'),
('a3333333-3333-3333-3333-333333333333', 2, 'How often do you compare yourself to others and feel you come up short?', 'scale', 1, 10, 'Rarely', 'Constantly', 'comparison_frequency'),
('a3333333-3333-3333-3333-333333333333', 3, 'Rate your ability to forgive yourself after doing something you regret.', 'scale', 1, 10, 'I hold grudges against myself', 'I forgive myself easily', 'self_forgiveness'),
('a3333333-3333-3333-3333-333333333333', 4, 'Which of these self-care patterns describe you? (Select all that apply)', 'multi_select', 1, 10, NULL, NULL, 'self_care_patterns'),
('a3333333-3333-3333-3333-333333333333', 5, 'If you could say one kind thing to your younger self, what would it be?', 'open_text', 1, 10, NULL, NULL, 'self_compassion_depth');

UPDATE quiz_questions SET options = '[
    {"value": "a", "label": "Harsh and critical — ''You always mess things up''"},
    {"value": "b", "label": "Disappointed but measured — ''You should have known better''"},
    {"value": "c", "label": "Anxious and spiraling — ''What if this ruins everything?''"},
    {"value": "d", "label": "Gentle and understanding — ''It''s okay, everyone makes mistakes''"},
    {"value": "e", "label": "Analytical — ''What can I learn from this?''"},
    {"value": "f", "label": "Silent — I don''t notice an inner voice, I just feel bad"}
]'::jsonb
WHERE quiz_id = 'a3333333-3333-3333-3333-333333333333' AND question_order = 1;

UPDATE quiz_questions SET options = '[
    {"value": "a", "label": "I take care of others before myself"},
    {"value": "b", "label": "I push through exhaustion instead of resting"},
    {"value": "c", "label": "I have consistent self-care habits"},
    {"value": "d", "label": "I only take care of myself when I break down"},
    {"value": "e", "label": "I feel guilty when I prioritize myself"},
    {"value": "f", "label": "I know what I need but struggle to do it"}
]'::jsonb
WHERE quiz_id = 'a3333333-3333-3333-3333-333333333333' AND question_order = 4;

-- =============================================================================
-- QUIZ 4: Meaning & Purpose (Day 4)
-- =============================================================================
INSERT INTO quizzes (id, title, description, theme, dimension, quiz_order, is_final)
VALUES (
    'a4444444-4444-4444-4444-444444444444',
    'The Compass',
    'What pulls you forward? This quiz explores where you find meaning, how you navigate uncertainty, and what happens when life challenges your sense of purpose.',
    'Meaning & Purpose',
    'meaning_making',
    4,
    FALSE
);

INSERT INTO quiz_questions (quiz_id, question_order, question_text, question_type, scale_min, scale_max, scale_min_label, scale_max_label, dimension_tag) VALUES
('a4444444-4444-4444-4444-444444444444', 1, 'How clear is your sense of purpose or direction in life right now?', 'scale', 1, 10, 'Completely lost', 'Crystal clear', 'purpose_clarity'),
('a4444444-4444-4444-4444-444444444444', 2, 'When life feels meaningless or empty, what do you turn to?', 'multiple_choice', 1, 10, NULL, NULL, 'meaning_source'),
('a4444444-4444-4444-4444-444444444444', 3, 'How do you typically respond when something you deeply believed in turns out to be wrong?', 'multiple_choice', 1, 10, NULL, NULL, 'belief_flexibility'),
('a4444444-4444-4444-4444-444444444444', 4, 'Rank these from most to least important to your sense of well-being.', 'ranking', 1, 10, NULL, NULL, 'values_hierarchy'),
('a4444444-4444-4444-4444-444444444444', 5, 'What would you want someone to remember about you long after you''re gone?', 'open_text', 1, 10, NULL, NULL, 'legacy_vision');

UPDATE quiz_questions SET options = '[
    {"value": "a", "label": "Relationships — I call someone I love"},
    {"value": "b", "label": "Creation — I make something (art, writing, building)"},
    {"value": "c", "label": "Nature — I go outside and reconnect with the world"},
    {"value": "d", "label": "Service — I help someone else"},
    {"value": "e", "label": "Spirituality — I pray, meditate, or seek something transcendent"},
    {"value": "f", "label": "Distraction — I keep busy until the feeling passes"}
]'::jsonb
WHERE quiz_id = 'a4444444-4444-4444-4444-444444444444' AND question_order = 2;

UPDATE quiz_questions SET options = '[
    {"value": "a", "label": "I feel devastated — my identity shakes"},
    {"value": "b", "label": "I get curious — what else might I be wrong about?"},
    {"value": "c", "label": "I resist it — I look for evidence I was right"},
    {"value": "d", "label": "I adapt quickly — beliefs are meant to evolve"},
    {"value": "e", "label": "I grieve it, then move forward"},
    {"value": "f", "label": "I shut down — it''s too overwhelming to reconsider"}
]'::jsonb
WHERE quiz_id = 'a4444444-4444-4444-4444-444444444444' AND question_order = 3;

UPDATE quiz_questions SET options = '[
    {"value": "connection", "label": "Deep connection with others"},
    {"value": "autonomy", "label": "Freedom and autonomy"},
    {"value": "growth", "label": "Personal growth and learning"},
    {"value": "security", "label": "Safety and security"},
    {"value": "impact", "label": "Making an impact on the world"},
    {"value": "joy", "label": "Joy and pleasure"}
]'::jsonb
WHERE quiz_id = 'a4444444-4444-4444-4444-444444444444' AND question_order = 4;

-- =============================================================================
-- QUIZ 5: Integration & Legacy (Day 5 — FINAL)
-- =============================================================================
INSERT INTO quizzes (id, title, description, theme, dimension, quiz_order, is_final)
VALUES (
    'a5555555-5555-5555-5555-555555555555',
    'The Threshold',
    'This is the final step. Everything you''ve explored — your awareness, your connections, your inner voice, your sense of purpose — converges here. This quiz asks: Who are you becoming?',
    'Integration & Legacy',
    'integration',
    5,
    TRUE
);

INSERT INTO quiz_questions (quiz_id, question_order, question_text, question_type, scale_min, scale_max, scale_min_label, scale_max_label, dimension_tag) VALUES
('a5555555-5555-5555-5555-555555555555', 1, 'Looking at your life as a whole, how coherent does your emotional experience feel — like the pieces fit together?', 'scale', 1, 10, 'Fragmented and chaotic', 'Integrated and whole', 'coherence_self_rating'),
('a5555555-5555-5555-5555-555555555555', 2, 'What is the single biggest thing standing between you and the person you want to become?', 'multiple_choice', 1, 10, NULL, NULL, 'primary_barrier'),
('a5555555-5555-5555-5555-555555555555', 3, 'If you could change one pattern in your emotional life starting today, what would it be?', 'open_text', 1, 10, NULL, NULL, 'change_priority'),
('a5555555-5555-5555-5555-555555555555', 4, 'How ready are you to actively work on your emotional growth with guidance?', 'scale', 1, 10, 'Not ready at all', 'Completely ready', 'readiness_for_change'),
('a5555555-5555-5555-5555-555555555555', 5, 'Write a letter to yourself one year from now. What do you hope has changed?', 'open_text', 1, 10, NULL, NULL, 'future_self_letter');

UPDATE quiz_questions SET options = '[
    {"value": "a", "label": "Fear — I''m afraid of what might happen if I change"},
    {"value": "b", "label": "Self-doubt — I don''t believe I can do it"},
    {"value": "c", "label": "Old wounds — Unresolved pain keeps pulling me back"},
    {"value": "d", "label": "Isolation — I don''t have enough support"},
    {"value": "e", "label": "Habits — My patterns are deeply ingrained"},
    {"value": "f", "label": "Time — I''m too overwhelmed with life to work on myself"},
    {"value": "g", "label": "Nothing specific — I just don''t know where to start"}
]'::jsonb
WHERE quiz_id = 'a5555555-5555-5555-5555-555555555555' AND question_order = 2;

-- =============================================================================
-- SEED: Default Campaign with 5 Steps
-- =============================================================================
INSERT INTO campaigns (id, name, description, status, conversion_window_days)
VALUES (
    'c0000000-0000-0000-0000-000000000001',
    'Emotional Coherence 5-Day Journey',
    'The flagship drip campaign. Five days, five quizzes, five insights. Prospects explore their emotional landscape with Little Nate, culminating in a full coaching assessment and Golden Ticket.',
    'draft',
    7
);

INSERT INTO campaign_steps (campaign_id, step_order, delay_hours, email_subject, quiz_id, sms_enabled, sms_template) VALUES
('c0000000-0000-0000-0000-000000000001', 1, 0,   'Day 1: The Mirror — How Well Do You See Yourself?', 'a1111111-1111-1111-1111-111111111111', TRUE, 'Hi {{first_name}}! Your first Emotional Coherence quiz is ready. Check your email from Sovereign Sanctuary. Reply STOP to opt out.'),
('c0000000-0000-0000-0000-000000000001', 2, 24,  'Day 2: The Bridge — How Do You Connect?', 'a2222222-2222-2222-2222-222222222222', TRUE, 'Day 2 of your journey with Nate is here, {{first_name}}. Check your email! Reply STOP to opt out.'),
('c0000000-0000-0000-0000-000000000001', 3, 24,  'Day 3: The Voice Inside — What Does Your Inner Dialogue Sound Like?', 'a3333333-3333-3333-3333-333333333333', TRUE, 'Day 3: Nate has a new question for you. Check your email from Sovereign Sanctuary. Reply STOP to opt out.'),
('c0000000-0000-0000-0000-000000000001', 4, 24,  'Day 4: The Compass — What Pulls You Forward?', 'a4444444-4444-4444-4444-444444444444', TRUE, 'Almost there, {{first_name}}! Day 4 awaits. Check your email. Reply STOP to opt out.'),
('c0000000-0000-0000-0000-000000000001', 5, 24,  'Day 5: The Threshold — Who Are You Becoming?', 'a5555555-5555-5555-5555-555555555555', TRUE, 'Final day! Your assessment and Golden Ticket are almost ready. Check your email. Reply STOP to opt out.');

-- =============================================================================
-- END OF SEED DATA
-- =============================================================================

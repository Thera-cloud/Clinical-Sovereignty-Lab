-- Classroom Learning Auditor — trust baseline (15 DB checks across 5 tabs)
INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES (
    'classroom_learning_check_count',
    '{"expected": 15, "description": "Classroom Learning: Schema (3) + Session analyses (3) + Coaching sessions (3) + Wisdom sinks (3) + Crystals & consistency (3)"}'
)
ON CONFLICT (parameter_key) DO UPDATE SET parameter_value = EXCLUDED.parameter_value;

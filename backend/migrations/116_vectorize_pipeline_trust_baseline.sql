-- Migration 116: Vectorize Pipeline Trust Baseline
-- Adds the trust baseline entry for the Vectorize Pipeline Auditor (30th auditor).
-- 12 checks: 2 embedding health + 3 push pipeline + 6 retrieval quality + 1 data integrity

INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES ('vectorize_pipeline_check_count', '{"expected": 12, "description": "Vectorize Pipeline: 2 embed + 3 push + 6 retrieval + 1 data integrity"}'::jsonb)
ON CONFLICT (parameter_key) DO UPDATE SET parameter_value = EXCLUDED.parameter_value;

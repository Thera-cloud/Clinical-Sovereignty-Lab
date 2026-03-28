-- Migration 130: Update Vectorize Pipeline baseline from 12 to 13 checks
-- Added nate-predictive index (7th Vectorize index) for cycle detections + foresight alerts

UPDATE trust_baseline
SET parameter_value = '{"expected": 13, "description": "Vectorize Pipeline: 2 embed + 3 push + 7 retrieval + 1 data integrity"}'::jsonb
WHERE parameter_key = 'vectorize_pipeline_check_count';

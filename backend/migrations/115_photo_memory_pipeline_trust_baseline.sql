-- Migration 115: Photo & Memory Pipeline Auditor trust baseline
-- Registers the expected check count (16) for the new data-verification auditor.

INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES ('photo_memory_pipeline_check_count', '{"expected": 16, "description": "Photo & Memory Pipeline: 5 conv history DB + 4 sync REST + 4 photo analysis DB + 2 memory search REST + 1 cross-pipeline integrity"}'::jsonb)
ON CONFLICT (parameter_key) DO UPDATE SET parameter_value = EXCLUDED.parameter_value;

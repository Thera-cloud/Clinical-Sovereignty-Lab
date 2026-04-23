-- Clinical translation: coach-facing interpretation of Thera-World / SSE panels

ALTER TABLE sse_delivery_generation_log
    ADD COLUMN IF NOT EXISTS clinical_translation TEXT;

ALTER TABLE sse_panel_log
    ADD COLUMN IF NOT EXISTS clinical_translation TEXT;

CREATE INDEX IF NOT EXISTS idx_sse_gen_log_clinical
    ON sse_delivery_generation_log (user_id, generated_at DESC)
    WHERE clinical_translation IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_sse_panel_log_clinical
    ON sse_panel_log (user_id, generated_at DESC)
    WHERE clinical_translation IS NOT NULL;

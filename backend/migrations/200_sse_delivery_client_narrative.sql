-- Client-facing therapeutic narrative for delivery-log assets (distinct from image/video prompt_used).

ALTER TABLE sse_delivery_generation_log
    ADD COLUMN IF NOT EXISTS client_narrative_text TEXT;

CREATE INDEX IF NOT EXISTS idx_sse_gen_log_client_narr
    ON sse_delivery_generation_log (user_id, generated_at DESC)
    WHERE client_narrative_text IS NOT NULL AND btrim(client_narrative_text) <> '';

-- QUANTUM-CRYSTAL-ARCH: Journey recap story video jobs (30s stitched Thera-World recap)
CREATE TABLE IF NOT EXISTS sse_journey_recap_jobs (
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'aligning', 'rendering', 'clips_ready', 'stitching', 'complete', 'failed')),
    transcript_text TEXT NOT NULL,
    audio_r2_key TEXT,
    audio_r2_url TEXT,
    panel_alignments JSONB NOT NULL DEFAULT '[]'::jsonb,
    chat_captures JSONB NOT NULL DEFAULT '[]'::jsonb,
    segment_clips JSONB NOT NULL DEFAULT '[]'::jsonb,
    output_r2_key TEXT,
    output_r2_url TEXT,
    target_duration_seconds INT NOT NULL DEFAULT 30,
    segment_count INT NOT NULL DEFAULT 4,
    archetype_hint TEXT,
    archetype_image_url TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_sse_journey_recap_jobs_user
    ON sse_journey_recap_jobs (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_sse_journey_recap_jobs_status
    ON sse_journey_recap_jobs (status, created_at DESC);

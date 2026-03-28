-- Migration 126: Call Metrics table for Metrics Helix Agent
-- Stores 10 per-call coherence metrics computed in real-time

CREATE TABLE IF NOT EXISTS call_metrics (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    call_id         UUID NOT NULL,
    user_id         VARCHAR(255),
    call_sid        VARCHAR(255),
    response_gap_ms FLOAT DEFAULT 0,
    caller_wpm      FLOAT DEFAULT 0,
    nate_wpm        FLOAT DEFAULT 0,
    coherence_score FLOAT DEFAULT 0,
    cee_window_detected FLOAT DEFAULT 0,
    emotional_valence_shift FLOAT DEFAULT 0,
    silence_ratio   FLOAT DEFAULT 0,
    topic_continuity FLOAT DEFAULT 0,
    engagement_depth FLOAT DEFAULT 0,
    call_quality_composite FLOAT DEFAULT 0,
    computed_at     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(call_id)
);

CREATE INDEX IF NOT EXISTS idx_call_metrics_user ON call_metrics(user_id);
CREATE INDEX IF NOT EXISTS idx_call_metrics_computed ON call_metrics(computed_at DESC);

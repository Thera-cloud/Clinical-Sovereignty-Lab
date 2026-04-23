-- Client assessment results for Thera-World / AssessmentBridge calibration

CREATE TABLE IF NOT EXISTS assessment_results (
    id              SERIAL PRIMARY KEY,
    user_id         VARCHAR NOT NULL,
    assessment_type VARCHAR NOT NULL,
    scores          JSONB DEFAULT '{}'::jsonb,
    result_summary  TEXT,
    status          VARCHAR DEFAULT 'completed',
    completed_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_assessment_results_user_completed
    ON assessment_results (user_id, completed_at DESC);

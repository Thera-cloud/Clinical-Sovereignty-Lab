-- SSE Stage 7 — Intelligence layer tables

CREATE TABLE IF NOT EXISTS sse_clinical_review_log (
    review_id       UUID PRIMARY KEY,
    storyboard_id   TEXT,
    phase_id        TEXT,
    concern         TEXT,
    recommendation  TEXT,
    flagged_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved        BOOL NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS idx_sse_clinical_review_sb   ON sse_clinical_review_log (storyboard_id);
CREATE INDEX IF NOT EXISTS idx_sse_clinical_review_phase ON sse_clinical_review_log (phase_id);

CREATE TABLE IF NOT EXISTS sse_delivery_outcomes (
    outcome_id      UUID PRIMARY KEY,
    storyboard_id   TEXT,
    user_id         TEXT,
    phase_id        TEXT,
    outcome         TEXT,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sse_outcomes_sb   ON sse_delivery_outcomes (storyboard_id);
CREATE INDEX IF NOT EXISTS idx_sse_outcomes_user ON sse_delivery_outcomes (user_id);

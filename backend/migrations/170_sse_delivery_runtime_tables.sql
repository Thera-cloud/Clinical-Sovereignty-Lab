-- SSE Stage 5 — Delivery runtime tables

-- Generation audit log (append-only)
CREATE TABLE IF NOT EXISTS sse_delivery_generation_log (
    log_id          UUID PRIMARY KEY,
    storyboard_id   TEXT,
    user_id         TEXT,
    generation_type TEXT,
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    r2_url          TEXT,
    prompt_used     TEXT,
    score           FLOAT,
    cost            FLOAT,
    status          TEXT,
    error_message   TEXT
);
CREATE INDEX IF NOT EXISTS idx_sse_gen_log_sb   ON sse_delivery_generation_log (storyboard_id);
CREATE INDEX IF NOT EXISTS idx_sse_gen_log_user ON sse_delivery_generation_log (user_id);

-- Gap tracking for progressive recovery
CREATE TABLE IF NOT EXISTS sse_delivery_gap_log (
    gap_id        UUID PRIMARY KEY,
    storyboard_id TEXT,
    user_id       TEXT,
    gap_date      DATE,
    gap_type      TEXT,
    recovered     BOOL NOT NULL DEFAULT false,
    abandoned     BOOL NOT NULL DEFAULT false,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sse_gap_sb   ON sse_delivery_gap_log (storyboard_id);
CREATE INDEX IF NOT EXISTS idx_sse_gap_user ON sse_delivery_gap_log (user_id);

-- Cost circuit breaker events
CREATE TABLE IF NOT EXISTS sse_cost_circuit_breaker (
    breaker_id    UUID PRIMARY KEY,
    storyboard_id TEXT,
    triggered_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    daily_spend   FLOAT,
    monthly_spend FLOAT,
    reason        TEXT,
    resumed_at    TIMESTAMPTZ,
    status        TEXT NOT NULL DEFAULT 'tripped'
);
CREATE INDEX IF NOT EXISTS idx_sse_breaker_sb ON sse_cost_circuit_breaker (storyboard_id);

-- Orchestrator heartbeat log
CREATE TABLE IF NOT EXISTS sse_delivery_heartbeat (
    heartbeat_id       UUID PRIMARY KEY,
    checked_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    storyboards_checked INT,
    gaps_found         INT,
    status             TEXT,
    notes              TEXT
);

-- Enrolled users per storyboard
CREATE TABLE IF NOT EXISTS sse_enrolled_users (
    enrollment_id UUID PRIMARY KEY,
    user_id       TEXT NOT NULL,
    storyboard_id TEXT NOT NULL,
    current_phase TEXT,
    enrolled_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status        TEXT NOT NULL DEFAULT 'active',
    ec_score      FLOAT,
    UNIQUE (user_id, storyboard_id)
);
CREATE INDEX IF NOT EXISTS idx_sse_enrolled_sb   ON sse_enrolled_users (storyboard_id);
CREATE INDEX IF NOT EXISTS idx_sse_enrolled_user ON sse_enrolled_users (user_id);

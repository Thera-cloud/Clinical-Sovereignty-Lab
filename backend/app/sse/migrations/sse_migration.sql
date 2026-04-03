-- SSE Stage 4 — Deployment tables
-- Canonical copy lives at backend/migrations/169_sse_deployment_tables.sql

-- Delivery configuration per storyboard
CREATE TABLE IF NOT EXISTS sse_delivery_config (
    config_id       UUID PRIMARY KEY,
    storyboard_id   TEXT NOT NULL,
    delivery_config JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status          TEXT NOT NULL DEFAULT 'active',
    version         INT NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_sse_delivery_config_storyboard
    ON sse_delivery_config (storyboard_id);

-- Cron schedule entries for automated generation
CREATE TABLE IF NOT EXISTS sse_cron_schedules (
    schedule_id     UUID PRIMARY KEY,
    storyboard_id   TEXT NOT NULL,
    schedule_type   TEXT NOT NULL,
    cron_expression TEXT NOT NULL,
    target_tier     TEXT,
    enabled         BOOL NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sse_cron_schedules_storyboard
    ON sse_cron_schedules (storyboard_id);

-- Deployment audit log (append-only)
CREATE TABLE IF NOT EXISTS sse_deployment_log (
    log_id            UUID PRIMARY KEY,
    storyboard_id     TEXT NOT NULL,
    provenance_id     TEXT,
    action            TEXT NOT NULL,
    config_id         TEXT,
    objects_promoted  INT,
    schedule_ids      JSONB,
    deployed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status            TEXT NOT NULL,
    notes             TEXT
);
CREATE INDEX IF NOT EXISTS idx_sse_deployment_log_storyboard
    ON sse_deployment_log (storyboard_id);

-- Imagery generation results
CREATE TABLE IF NOT EXISTS sse_imagery_results (
    result_id         UUID PRIMARY KEY,
    storyboard_id     TEXT NOT NULL,
    panels_generated  INT,
    panels_failed     INT,
    estimated_cost    TEXT,
    results           JSONB,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sse_imagery_results_storyboard
    ON sse_imagery_results (storyboard_id);

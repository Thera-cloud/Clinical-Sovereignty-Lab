-- Migration 144: Command Terminal V2 — Sovereign IDE tables
-- Supports: cli_tool_calls audit trail, plan accept/revoke governance

CREATE TABLE IF NOT EXISTS cli_tool_calls (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id         TEXT NOT NULL,
    request_id      UUID,
    tool_name       TEXT NOT NULL,
    tool_input      JSONB,
    tool_output     JSONB,
    status          TEXT DEFAULT 'completed',
    duration_ms     INT,
    decision        TEXT,
    decided_by      TEXT,
    decided_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cli_tool_calls_plan
    ON cli_tool_calls (plan_id);
CREATE INDEX IF NOT EXISTS idx_cli_tool_calls_request
    ON cli_tool_calls (request_id);
CREATE INDEX IF NOT EXISTS idx_cli_tool_calls_created
    ON cli_tool_calls (created_at);

-- Track accept/revoke state on artifacts
ALTER TABLE cli_mode_artifacts
    ADD COLUMN IF NOT EXISTS review_status TEXT DEFAULT 'proposed';

-- Link repair requests to their originating plan
ALTER TABLE source_repair_requests
    ADD COLUMN IF NOT EXISTS plan_id TEXT;

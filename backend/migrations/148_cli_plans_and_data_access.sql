-- Migration 148: CLI Plans lifecycle registry + data access audit log
-- Supports: plan lifecycle tracking, RBAC audit trail, session persistence

CREATE TABLE IF NOT EXISTS cli_plans (
    plan_id         TEXT PRIMARY KEY,
    mode            VARCHAR(10) NOT NULL CHECK (mode IN ('ask', 'plan', 'ln_fab', 'debug')),
    cli_type        VARCHAR(10) NOT NULL CHECK (cli_type IN ('mac', 'cloud')),
    status          VARCHAR(20) NOT NULL DEFAULT 'proposed'
                    CHECK (status IN ('proposed', 'in_progress', 'completed', 'abandoned')),
    title           TEXT,
    created_by      VARCHAR(100) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ,
    files           JSONB DEFAULT '[]'::jsonb,
    total_turns     INT DEFAULT 0,
    total_tool_calls INT DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_cli_plans_status
    ON cli_plans (status) WHERE status = 'in_progress';
CREATE INDEX IF NOT EXISTS idx_cli_plans_created
    ON cli_plans (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cli_plans_user
    ON cli_plans (created_by, created_at DESC);

-- Cost tracking columns for session-level analytics
ALTER TABLE cli_plans
    ADD COLUMN IF NOT EXISTS input_chars     BIGINT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS output_chars    BIGINT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS est_input_tokens  BIGINT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS est_output_tokens BIGINT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS est_cost_usd    NUMERIC(12,6) DEFAULT 0;

-- Extend cli_tool_calls with environment context
ALTER TABLE cli_tool_calls
    ADD COLUMN IF NOT EXISTS cli_type VARCHAR(10),
    ADD COLUMN IF NOT EXISTS user_role VARCHAR(20),
    ADD COLUMN IF NOT EXISTS turn_number INT;

-- Separate audit log for data-touching tool calls (HIPAA)
CREATE TABLE IF NOT EXISTS cli_data_access_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id         TEXT,
    username        VARCHAR(100) NOT NULL,
    tool_name       TEXT NOT NULL,
    data_scope      JSONB,
    result_row_count INT,
    role_tier       VARCHAR(20),
    data_classification VARCHAR(20) DEFAULT 'internal',
    redacted_args   JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cli_data_access_user
    ON cli_data_access_log (username, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cli_data_access_plan
    ON cli_data_access_log (plan_id);

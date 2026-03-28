-- Migration 140: Trust Enforcer run idempotency and execution ledger
-- Purpose:
--   1) DB-level idempotency guard for trust window/report execution
--   2) Durable execution trail for scheduled/manual runs

CREATE TABLE IF NOT EXISTS trust_enforcer_run_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    window_key TEXT NOT NULL,
    run_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    total_trusted INTEGER NOT NULL DEFAULT 0,
    total_tests INTEGER NOT NULL DEFAULT 0,
    preflight_passed INTEGER NOT NULL DEFAULT 0,
    preflight_total INTEGER NOT NULL DEFAULT 0,
    level TEXT,
    action_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    CONSTRAINT trust_enforcer_run_records_run_type_chk
        CHECK (run_type IN ('scheduled', 'manual')),
    CONSTRAINT trust_enforcer_run_records_status_chk
        CHECK (status IN ('running', 'sent', 'failed', 'skipped')),
    CONSTRAINT trust_enforcer_run_records_uq
        UNIQUE (window_key, run_type)
);

CREATE INDEX IF NOT EXISTS idx_trust_enforcer_runs_started_at
    ON trust_enforcer_run_records(started_at DESC);

CREATE INDEX IF NOT EXISTS idx_trust_enforcer_runs_window
    ON trust_enforcer_run_records(window_key, run_type);

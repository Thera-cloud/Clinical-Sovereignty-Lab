-- FIX-THERAPEUTIC-CONTROLLER
-- Per-turn therapeutic audit log: state classification, register used,
-- mismatch attempts, audit pass/fail, banned-phrase violations.
-- Additive only; consumed by the therapeutic_controller post-flight audit.

CREATE TABLE IF NOT EXISTS sse_therapeutic_audit_log (
    audit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    autonomic_state TEXT,
    tmc_class TEXT,
    register_used TEXT,
    mismatch_attempted BOOLEAN,
    mismatch_delivered BOOLEAN,
    audit_passed BOOLEAN,
    audit_violations JSONB,
    response_token_count INTEGER,
    encoded_patterns JSONB
);

CREATE INDEX IF NOT EXISTS idx_audit_log_user
    ON sse_therapeutic_audit_log(user_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_audit_log_failures
    ON sse_therapeutic_audit_log(timestamp DESC)
    WHERE audit_passed = false;

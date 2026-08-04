-- Thera-World Global Symbol Safety System — Layer D3.4 persistence.
-- One row per vision-gate check (pass, fail, retry, fallback, or gate-unavailable)
-- so every panel delivery decision is auditable regardless of outcome.
-- Additive only. Never DROP/ALTER existing tables.

CREATE TABLE IF NOT EXISTS sse_symbol_gate_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    panel_id TEXT,
    attempt INTEGER NOT NULL DEFAULT 1,
    checked_symbols JSONB NOT NULL DEFAULT '[]'::jsonb,
    violations JSONB NOT NULL DEFAULT '[]'::jsonb,
    gate_available BOOLEAN NOT NULL DEFAULT TRUE,
    outcome TEXT NOT NULL,  -- 'clean' | 'violation_detected' | 'fallback_safe_template' | 'gate_unavailable'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sse_symbol_gate_log_user
    ON sse_symbol_gate_log(user_id);

CREATE INDEX IF NOT EXISTS idx_sse_symbol_gate_log_outcome
    ON sse_symbol_gate_log(outcome);

-- QUANTUM-CRYSTAL-ARCH: L3b gate confidence + L4 rule-store scaffold
-- L3a uses existing crystal_outcome_view (migration 236) — no schema needed.

CREATE TABLE IF NOT EXISTS clinical_gate_confidence (
    gate_key        TEXT PRIMARY KEY,
    confidence      REAL NOT NULL DEFAULT 0.70
                    CHECK (confidence >= 0.05 AND confidence <= 0.99),
    sample_size     INTEGER NOT NULL DEFAULT 0,
    positive_count  INTEGER NOT NULL DEFAULT 0,
    negative_count  INTEGER NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reasoning       TEXT
);

COMMENT ON TABLE clinical_gate_confidence IS
    'L3b — rolling confidence per clinical runtime-gate class. Soft follow-ups '
    'may be suppressed when confidence is low; hard SI/crisis paths never consult this.';

CREATE TABLE IF NOT EXISTS ln_rule_store (
    id              BIGSERIAL PRIMARY KEY,
    rule_key        TEXT NOT NULL,
    version         INTEGER NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'sandbox', 'active', 'rolled_back')),
    condition_json  JSONB NOT NULL DEFAULT '{}'::jsonb,
    action_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    promoted_at     TIMESTAMPTZ,
    rolled_back_at  TIMESTAMPTZ,
    created_by      TEXT NOT NULL DEFAULT 'system',
    notes           TEXT,
    UNIQUE (rule_key, version)
);

CREATE INDEX IF NOT EXISTS idx_ln_rule_store_active
    ON ln_rule_store (rule_key, status)
    WHERE status = 'active';

COMMENT ON TABLE ln_rule_store IS
    'L4 scaffold — versioned condition/action rules. ENABLE_LN_RULE_LOOP must be '
    'on before any draft→sandbox→promote path mutates live turn behavior.';

CREATE TABLE IF NOT EXISTS ln_rule_audit (
    id              BIGSERIAL PRIMARY KEY,
    rule_key        TEXT NOT NULL,
    version         INTEGER NOT NULL,
    action          TEXT NOT NULL
                    CHECK (action IN ('draft', 'sandbox_pass', 'sandbox_fail', 'promote', 'rollback')),
    detail          TEXT,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

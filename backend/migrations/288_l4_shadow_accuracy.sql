-- QUANTUM-CRYSTAL-ARCH: L4 shadow-vs-actual accuracy (evidence layer under auto-promote)
-- Soft-gate rules only. Never stores SI/violence/coach-routing classes.

CREATE TABLE IF NOT EXISTS ln_rule_shadow_scores (
    id                      BIGSERIAL PRIMARY KEY,
    rule_key                TEXT NOT NULL,
    version                 INTEGER NOT NULL,
    phase                   TEXT NOT NULL
                            CHECK (phase IN ('shadow', 'post_promote')),
    predicted_action        TEXT NOT NULL DEFAULT 'suppress_soft_followup',
    predicted_would_suppress BOOLEAN NOT NULL,
    gate_class              TEXT,
    match_confidence        REAL,
    actual_suppressed       BOOLEAN,
    actual_label            TEXT
                            CHECK (
                                actual_label IS NULL
                                OR actual_label IN ('tp', 'fp', 'tn', 'fn', 'pending')
                            ),
    recorded_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ln_rule_shadow_scores_key_ver
    ON ln_rule_shadow_scores (rule_key, version, phase);

COMMENT ON TABLE ln_rule_shadow_scores IS
    'L4 Phase-3 evidence — counterfactual shadow predictions vs post-promote actuals. '
    'Auto-promote is untrustworthy until shadow tracks reality.';

-- Audit: mark accuracy snapshots explicitly (optional action)
ALTER TABLE ln_rule_audit DROP CONSTRAINT IF EXISTS ln_rule_audit_action_check;
ALTER TABLE ln_rule_audit ADD CONSTRAINT ln_rule_audit_action_check
    CHECK (action IN (
        'draft', 'sandbox_pass', 'sandbox_fail', 'promote', 'rollback',
        'fire', 'shadow_fire', 'accuracy_report'
    ));

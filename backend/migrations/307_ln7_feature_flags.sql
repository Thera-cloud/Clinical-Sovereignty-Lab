-- LN7 / flywheel feature flags (W6). PG-first; env is emergency kill-switch.
-- QUANTUM-CRYSTAL-ARCH
-- Additive only.

CREATE TABLE IF NOT EXISTS ln7_feature_flags (
    key             TEXT PRIMARY KEY,
    enabled         BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes           TEXT
);

INSERT INTO ln7_feature_flags (key, enabled, notes) VALUES
    ('ENABLE_LN7_AUTO_PROMOTE', FALSE, 'G2: flip only after Step 0 fence green'),
    ('DUAL_COO_MECHANICAL_PROMOTE', FALSE, 'G2: Dual-COO checklist replaces CEO promote'),
    ('ENABLE_LN7_DOMAIN_ROUTER', FALSE, 'B2 domain router'),
    ('PHASE_H_OPEN', FALSE, 'Therapeutic weight loop predicates 5/5'),
    ('LN7_SERVE_ENGINE', FALSE, 'true when vllm_burst Redis endpoint active (semantic on)')
ON CONFLICT (key) DO NOTHING;

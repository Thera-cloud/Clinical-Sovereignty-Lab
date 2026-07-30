-- LN7 Milestone A: allow one active revision per serving tier (fast vs deep).
-- QUANTUM-CRYSTAL-ARCH
-- Additive: drop global one-active unique; replace with per-tier unique on harness tier.

DROP INDEX IF EXISTS idx_ln7_revisions_one_active;

CREATE UNIQUE INDEX IF NOT EXISTS idx_ln7_revisions_one_active_per_tier
    ON ln7_revisions (
        (COALESCE(NULLIF(TRIM(harness_config_json->>'tier'), ''), 'deep'))
    )
    WHERE active = TRUE;

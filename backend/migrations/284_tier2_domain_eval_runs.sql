-- QUANTUM-CRYSTAL-ARCH — Tier 2 cross-domain battery scoreboard stub (design spike)
-- Not certification. Scoreboard v0 may still use pgsd_cross_domain_agreement.

CREATE TABLE IF NOT EXISTS tier2_domain_eval_runs (
    id              BIGSERIAL PRIMARY KEY,
    pack_id         TEXT NOT NULL,
    domain          TEXT NOT NULL
                    CHECK (domain IN ('therapy', 'family', 'dojo', 'voice', 'ops')),
    environment     TEXT NOT NULL DEFAULT 'production',
    status          TEXT NOT NULL DEFAULT 'designed'
                    CHECK (status IN ('designed', 'running', 'scored', 'failed')),
    scores_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    privacy_ok      BOOLEAN,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    scored_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_tier2_domain_eval_pack
    ON tier2_domain_eval_runs (pack_id, created_at DESC);

COMMENT ON TABLE tier2_domain_eval_runs IS
  'Tier 2 Narrow AGI design spike — domain eval runs; not a certification ledger';

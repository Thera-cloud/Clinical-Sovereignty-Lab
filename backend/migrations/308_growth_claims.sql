-- Marketing growth claims registry (Phase M2 / W11).
-- QUANTUM-CRYSTAL-ARCH
-- Additive only.

CREATE TABLE IF NOT EXISTS growth_claims (
    claim_id            TEXT PRIMARY KEY,
    claim_text          TEXT NOT NULL,
    evidence_class      TEXT NOT NULL
                        CHECK (evidence_class IN (
                            'short_horizon', 'long_horizon', 'advisory'
                        )),
    artifact_uri        TEXT,
    envelope_id         UUID,
    expires_at          TIMESTAMPTZ,
    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN (
                            'active', 'expired', 'retracted', 'draft'
                        )),
    surface_map_json    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_growth_claims_status
    ON growth_claims (status, expires_at);

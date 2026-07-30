-- Living CI pack candidates from Queens merges (R2 / W8).
-- QUANTUM-CRYSTAL-ARCH
-- Additive only.

CREATE TABLE IF NOT EXISTS ln7_pack_candidates (
    id              BIGSERIAL PRIMARY KEY,
    patch_hash      TEXT NOT NULL,
    domain          TEXT,
    evidence_uri    TEXT,
    merged_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    distilled_at    TIMESTAMPTZ,
    pack_name       TEXT,
    split           TEXT CHECK (split IS NULL OR split IN ('train', 'heldout')),
    retired_at      TIMESTAMPTZ,
    revert_seen     BOOLEAN NOT NULL DEFAULT FALSE,
    metadata_json   JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (patch_hash)
);

CREATE INDEX IF NOT EXISTS idx_ln7_pack_candidates_pending
    ON ln7_pack_candidates (merged_at)
    WHERE distilled_at IS NULL AND retired_at IS NULL AND revert_seen = FALSE;

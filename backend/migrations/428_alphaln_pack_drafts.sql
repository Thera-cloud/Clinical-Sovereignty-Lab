-- Migration 428: AlphaLN fuel-pack drafts (human accept required)
--
-- AlphaLN may propose unique CI pack specs. Rows stay status=draft until
-- DrNevedal1 accepts. Accept materializes catalog_aln_* on the writable
-- packs root. Never writes outcome_envelope, crystals, or conversation_history.
-- Never calls fuel burst / drip.
--
-- Feature flag: ENABLE_ALPHALN_TWIN (same dark-ship as the rest of AlphaLN).

CREATE TABLE IF NOT EXISTS alphaln_pack_drafts (
    id                 BIGSERIAL PRIMARY KEY,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by         TEXT NOT NULL,
    slug               TEXT NOT NULL,
    title              TEXT NOT NULL,
    spec_json          JSONB NOT NULL,
    status             TEXT NOT NULL DEFAULT 'draft'
                       CHECK (status IN ('draft', 'accepted', 'rejected')),
    reviewed_by        TEXT,
    reviewed_at        TIMESTAMPTZ,
    pack_name          TEXT,
    reject_reason      TEXT,
    metadata           JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_alphaln_pack_drafts_slug_open
    ON alphaln_pack_drafts (slug)
    WHERE status IN ('draft', 'accepted');

CREATE INDEX IF NOT EXISTS idx_alphaln_pack_drafts_status
    ON alphaln_pack_drafts (status, created_at DESC);

COMMENT ON TABLE alphaln_pack_drafts IS
    'AlphaLN-authored CI pack specs. Human accept required before drip can see them.';

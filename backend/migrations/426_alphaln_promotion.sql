-- Migration 426: AlphaLN Slice 8 — Promotion pipeline (paved but locked)
--
-- Records AlphaLN promotion *candidates* (proposals to elevate a variant or
-- prompt-pack into the live Little Nate router). Enforcement gates:
--
--   1. `auto_promote_enabled()` in nate_clinical_flags.py MUST return False
--      (hardcoded — see cursor rule alphaln-twin-isolation.mdc invariant 6).
--   2. The `/api/admin/alphaln/promotion/approve` endpoint requires MFA,
--      DrNevedal1, and a manual approval_note.
--   3. This migration does NOT touch nate_intelligence_crystals or any
--      model-serving surface. It only records intent.
--
-- Feature flag: ENABLE_ALPHALN_PROMOTION (default false).

CREATE TABLE IF NOT EXISTS alphaln_promotion_candidates (
    id                 BIGSERIAL PRIMARY KEY,
    proposed_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    proposed_by        TEXT NOT NULL DEFAULT 'alphaln_gym',
    variant_id         TEXT NOT NULL,          -- FK-in-spirit to nate_clinical_variants.variant_id
    reason             TEXT,
    evidence           JSONB NOT NULL DEFAULT '{}'::jsonb,  -- match ids, win-rates, judge scores
    status             TEXT NOT NULL DEFAULT 'proposed'
                       CHECK (status IN ('proposed','approved','rejected','withdrawn')),
    reviewed_by        TEXT,
    reviewed_at        TIMESTAMPTZ,
    approval_note      TEXT,
    metadata           JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_alphaln_promotion_status
    ON alphaln_promotion_candidates(status, proposed_at DESC);
CREATE INDEX IF NOT EXISTS idx_alphaln_promotion_variant
    ON alphaln_promotion_candidates(variant_id, proposed_at DESC);

COMMENT ON TABLE alphaln_promotion_candidates IS
    'AlphaLN Slice 8 promotion proposals. Paved-and-locked; no auto-promote path in code.';

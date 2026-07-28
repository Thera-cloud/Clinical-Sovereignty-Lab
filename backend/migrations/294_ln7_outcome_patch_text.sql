-- LN7 — persist unified diffs for clean preference / SFT export
-- QUANTUM-CRYSTAL-ARCH
-- Additive only.

ALTER TABLE ln7_coding_outcomes
    ADD COLUMN IF NOT EXISTS patch_text TEXT;

COMMENT ON COLUMN ln7_coding_outcomes.patch_text IS
    'Unified diff (or chosen patch body) for offline train export; never hash-only stubs.';

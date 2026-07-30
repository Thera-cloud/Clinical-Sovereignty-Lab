-- LN7 domain adapter registry columns (flywheel Phase B2 / W9).
-- QUANTUM-CRYSTAL-ARCH
-- Additive only. Do NOT reuse 303 (HumanEval seed).

ALTER TABLE ln7_revisions
    ADD COLUMN IF NOT EXISTS domain_tag TEXT,
    ADD COLUMN IF NOT EXISTS adapter_uri TEXT,
    ADD COLUMN IF NOT EXISTS vllm_lora_name TEXT,
    ADD COLUMN IF NOT EXISTS embedding JSONB,
    ADD COLUMN IF NOT EXISTS serve_weight NUMERIC(8, 4) NOT NULL DEFAULT 1.0,
    ADD COLUMN IF NOT EXISTS parent_revision TEXT;

CREATE INDEX IF NOT EXISTS idx_ln7_revisions_domain_tag
    ON ln7_revisions (domain_tag)
    WHERE domain_tag IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ln7_revisions_parent
    ON ln7_revisions (parent_revision)
    WHERE parent_revision IS NOT NULL;

-- Phase A0: quarantine magazine adapters trained on 1.5B base
UPDATE ln7_revisions
SET status = 'rejected',
    notes = CASE
        WHEN notes IS NULL OR notes = '' THEN 'base_mismatch_1p5b'
        WHEN notes LIKE '%base_mismatch_1p5b%' THEN notes
        ELSE notes || '; base_mismatch_1p5b'
    END
WHERE status IS DISTINCT FROM 'rejected'
  AND (
    lower(COALESCE(base_checkpoint, '')) LIKE '%1.5b%'
    OR lower(COALESCE(harness_config_json->>'hf_base', '')) LIKE '%1.5b%'
    OR lower(COALESCE(notes, '')) LIKE '%1.5b%'
  );

-- Per-window signing key for outcome_envelope (E4).
-- QUANTUM-CRYSTAL-ARCH
-- Additive only.

ALTER TABLE outcome_envelope
    ADD COLUMN IF NOT EXISTS sig        TEXT,
    ADD COLUMN IF NOT EXISTS sig_window TEXT;

-- Not partial-indexed on IS NOT NULL predicate to keep it usable for the
-- "find unsigned rows written before this migration deployed" backfill scan.
CREATE INDEX IF NOT EXISTS idx_outcome_envelope_sig_window
    ON outcome_envelope (sig_window);

-- Principal-Review: class routing + provenance outside crystal_text (quarantine-safe).
-- Additive only.

ALTER TABLE principal_review_library
  ADD COLUMN IF NOT EXISTS response_class TEXT,
  ADD COLUMN IF NOT EXISTS source_scenario TEXT,
  ADD COLUMN IF NOT EXISTS promoted_by TEXT;

COMMENT ON COLUMN principal_review_library.response_class IS
  'Gold response_class (e.g. escalate_or_safety) — crisis inject ranks by this, not recency';
COMMENT ON COLUMN principal_review_library.source_scenario IS
  'Stem id (AQ-1) kept here — never paste into crystal_text (battery quarantine heuristics)';
COMMENT ON COLUMN principal_review_library.promoted_by IS
  'Username who promoted notes→crystal (provenance when workers propose notes)';

CREATE INDEX IF NOT EXISTS idx_pr_library_response_class
  ON principal_review_library (response_class)
  WHERE response_class IS NOT NULL AND response_class <> '';

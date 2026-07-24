-- Principal-Review: conversation library + gold score safety veto.
-- Additive only. Sovereign Command Principal-Review tab (D.14b + wisdom library).

ALTER TABLE six_quotient_human_gold
  ADD COLUMN IF NOT EXISTS safety_veto TEXT;

COMMENT ON COLUMN six_quotient_human_gold.safety_veto IS
  'ok | fail | null — clinician safety veto on escalate_or_safety items';

CREATE TABLE IF NOT EXISTS principal_review_library (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic TEXT NOT NULL DEFAULT '',
    section TEXT NOT NULL DEFAULT 'general',
    client_says TEXT NOT NULL,
    principal_response TEXT NOT NULL DEFAULT '',
    nate_response TEXT NOT NULL DEFAULT '',
    source_kind TEXT NOT NULL DEFAULT 'principal_authored',
    source_ref TEXT,
    tags TEXT[] NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'draft',
    promoted_crystal_id UUID,
    gold_admin_run_id TEXT,
    created_by TEXT NOT NULL DEFAULT 'DrNevedal1',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT principal_review_library_status_chk
      CHECK (status IN ('draft', 'approved', 'promoted', 'archived')),
    CONSTRAINT principal_review_library_source_chk
      CHECK (source_kind IN (
        'gold_scored', 'coach_dojo', 'principal_authored',
        'generated_pair', 'night_school', 'sandbox'
      ))
);

CREATE INDEX IF NOT EXISTS idx_pr_library_status
  ON principal_review_library (status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_pr_library_section
  ON principal_review_library (section);
CREATE INDEX IF NOT EXISTS idx_pr_library_source
  ON principal_review_library (source_kind, source_ref);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pr_library_source_ref_uq
  ON principal_review_library (source_kind, source_ref)
  WHERE source_ref IS NOT NULL AND source_ref <> '';

COMMENT ON TABLE principal_review_library IS
  'Principal-Review conversation templates: principal answers + Nate answers for LN recall/wisdom';

-- QUANTUM-CRYSTAL-ARCH: promote web enrichments into searchable directory techniques

ALTER TABLE clinical_directory_enrichments
    ADD COLUMN IF NOT EXISTS technique_payload JSONB,
    ADD COLUMN IF NOT EXISTS promoted BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_clinical_dir_enrich_promoted
    ON clinical_directory_enrichments (promoted)
    WHERE promoted = TRUE AND status = 'active';

COMMENT ON COLUMN clinical_directory_enrichments.technique_payload IS
    'Synthetic technique dict merged into directory search when promoted=true.';
COMMENT ON COLUMN clinical_directory_enrichments.promoted IS
    'When true, technique_payload is searchable alongside seed JSON techniques.';

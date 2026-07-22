-- QUANTUM-CRYSTAL-ARCH: Clinical technique directory web enrichments (LN care-plan assist)

CREATE TABLE IF NOT EXISTS clinical_directory_enrichments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_text      TEXT NOT NULL,
    modality_hint   VARCHAR(80),
    technique_hint  VARCHAR(120),
    summary         TEXT NOT NULL,
    source_urls     JSONB NOT NULL DEFAULT '[]'::jsonb,
    user_id         VARCHAR(64),
    status          VARCHAR(16) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'archived', 'rejected')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_clinical_dir_enrich_created
    ON clinical_directory_enrichments (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_clinical_dir_enrich_query
    ON clinical_directory_enrichments USING gin (to_tsvector('english', coalesce(query_text,'') || ' ' || coalesce(summary,'')));

COMMENT ON TABLE clinical_directory_enrichments IS
    'Web-enriched adjunct notes for clinical technique directory; unverified public sources.';

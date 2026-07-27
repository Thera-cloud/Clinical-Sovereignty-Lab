-- QUANTUM-CRYSTAL-ARCH: Dual-COO patent idea library (mission categories, rank ≥90 gate)

CREATE TABLE IF NOT EXISTS patent_idea_library (
    id                  BIGSERIAL PRIMARY KEY,
    slug                TEXT NOT NULL UNIQUE,
    title               TEXT NOT NULL,
    primary_category    VARCHAR(32) NOT NULL
        CHECK (primary_category IN ('world_qol', 'platform', 'qec_quantum', 'queens_nate')),
    topics              TEXT[] NOT NULL DEFAULT '{}',
    source_patent_paths TEXT[] NOT NULL DEFAULT '{}',
    idea_summary        TEXT NOT NULL DEFAULT '',
    latest_reflection_md TEXT NOT NULL DEFAULT '',
    sandbox_path        TEXT,
    ide_path            TEXT,
    rank_score          NUMERIC(6,2) NOT NULL DEFAULT 0,
    rank_dimensions     JSONB NOT NULL DEFAULT '{}'::jsonb,
    library_status      VARCHAR(32) NOT NULL DEFAULT 'active'
        CHECK (library_status IN (
            'active', 'promoted', 'shelved', 'implemented',
            'published_ide', 'archived'
        )),
    parent_id           BIGINT REFERENCES patent_idea_library(id) ON DELETE SET NULL,
    promote_reason      VARCHAR(16),
    uncertainty         NUMERIC(8,4) NOT NULL DEFAULT 0,
    critique_md         TEXT NOT NULL DEFAULT '',
    embedding_hint      TEXT,
    dedupe_hash         TEXT,
    last_scored_at      TIMESTAMPTZ,
    next_renew_at       TIMESTAMPTZ,
    renewal_count       INT NOT NULL DEFAULT 0,
    promote_count       INT NOT NULL DEFAULT 0,
    ceo_feedback_note   TEXT,
    archived_at         TIMESTAMPTZ,
    archived_by         VARCHAR(32),
    archive_reason      TEXT,
    pre_archive_status  VARCHAR(32),
    proposed_by         TEXT NOT NULL DEFAULT 'dual_coo',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_patent_idea_library_status_score
    ON patent_idea_library (library_status, rank_score DESC);
CREATE INDEX IF NOT EXISTS idx_patent_idea_library_category
    ON patent_idea_library (primary_category, library_status);
CREATE INDEX IF NOT EXISTS idx_patent_idea_library_renew
    ON patent_idea_library (next_renew_at)
    WHERE library_status = 'active';
CREATE INDEX IF NOT EXISTS idx_patent_idea_library_dedupe
    ON patent_idea_library (dedupe_hash)
    WHERE dedupe_hash IS NOT NULL;

CREATE TABLE IF NOT EXISTS patent_idea_rank_history (
    id              BIGSERIAL PRIMARY KEY,
    library_id      BIGINT NOT NULL REFERENCES patent_idea_library(id) ON DELETE CASCADE,
    rank_score      NUMERIC(6,2) NOT NULL,
    rank_dimensions JSONB NOT NULL DEFAULT '{}'::jsonb,
    weight_snapshot JSONB,
    critique_applied BOOLEAN NOT NULL DEFAULT FALSE,
    reason          VARCHAR(32) NOT NULL DEFAULT 'initial',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_patent_idea_rank_history_lib
    ON patent_idea_rank_history (library_id, created_at DESC);

CREATE TABLE IF NOT EXISTS patent_rank_weight_state (
    id              SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    weights         JSONB NOT NULL,
    eta             NUMERIC(6,4) NOT NULL DEFAULT 0.02,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    update_count    INT NOT NULL DEFAULT 0
);

INSERT INTO patent_rank_weight_state (id, weights, eta, update_count)
VALUES (
    1,
    '{
        "novelty": 0.12,
        "claim_clarity": 0.12,
        "code_alignment": 0.12,
        "commercial_fit": 0.08,
        "prior_art_safety": 0.10,
        "portfolio_gap": 0.08,
        "world_qol_impact": 0.10,
        "platform_leverage": 0.10,
        "qec_depth": 0.10,
        "queens_nate_lift": 0.08,
        "proven_possibility": 0.10
    }'::jsonb,
    0.02,
    0
)
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS patent_rank_weight_history (
    id              BIGSERIAL PRIMARY KEY,
    weights_before  JSONB NOT NULL,
    weights_after   JSONB NOT NULL,
    reflection_id   BIGINT,
    decision        VARCHAR(32),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS patent_reflections (
    id                  BIGSERIAL PRIMARY KEY,
    library_id          BIGINT NOT NULL REFERENCES patent_idea_library(id) ON DELETE CASCADE,
    title               TEXT NOT NULL,
    primary_category    VARCHAR(32) NOT NULL,
    topics              TEXT[] NOT NULL DEFAULT '{}',
    source_patent_paths TEXT[] NOT NULL DEFAULT '{}',
    reflection_md       TEXT NOT NULL DEFAULT '',
    idea_summary        TEXT NOT NULL DEFAULT '',
    proposed_claims_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    sandbox_path        TEXT,
    ide_path            TEXT,
    promote_reason      VARCHAR(16) NOT NULL DEFAULT 'exploit',
    status              VARCHAR(32) NOT NULL DEFAULT 'pending'
        CHECK (status IN (
            'pending', 'inquiring', 'ready_for_decision',
            'approved_cli', 'approved_ide', 'rejected', 'held'
        )),
    risk_class          VARCHAR(16) NOT NULL DEFAULT 'YELLOW',
    ceo_item_id         TEXT,
    cli_task_id         TEXT,
    proposed_by         TEXT NOT NULL DEFAULT 'dual_coo',
    reviewed_at         TIMESTAMPTZ,
    reviewed_by         TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_patent_reflections_status
    ON patent_reflections (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_patent_reflections_library
    ON patent_reflections (library_id);

CREATE TABLE IF NOT EXISTS patent_reflection_inquiries (
    id              BIGSERIAL PRIMARY KEY,
    reflection_id   BIGINT NOT NULL REFERENCES patent_reflections(id) ON DELETE CASCADE,
    author          VARCHAR(32) NOT NULL
        CHECK (author IN ('ceo', 'dual_coo', 'queen_mac', 'queen_cloud')),
    body            TEXT NOT NULL,
    parent_id       BIGINT REFERENCES patent_reflection_inquiries(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_patent_reflection_inquiries_ref
    ON patent_reflection_inquiries (reflection_id, created_at ASC);

-- CEO Dual-COO auditor: 6 prior + 4 patent-library endpoints = 10
UPDATE trust_baseline
SET parameter_value = jsonb_set(
    COALESCE(parameter_value, '{}'::jsonb),
    '{expected}',
    '10'
)
WHERE parameter_key = 'ceo_dual_coo_check_count';

INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES (
    'ceo_dual_coo_check_count',
    '{"expected": 10, "description": "CEO Dual-COO inbox + patent library/review endpoints"}'::jsonb
)
ON CONFLICT (parameter_key) DO UPDATE
SET parameter_value = EXCLUDED.parameter_value;

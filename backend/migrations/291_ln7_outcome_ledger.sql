-- Little Nate 7 — outcome ledger, revisions, tasks, learning artifacts
-- QUANTUM-CRYSTAL-ARCH
-- Additive only.

CREATE TABLE IF NOT EXISTS ln7_revisions (
    revision_id         TEXT PRIMARY KEY,
    revised_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    base_checkpoint     TEXT NOT NULL,
    quantization        TEXT,
    harness_config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    notes               TEXT,
    active              BOOLEAN NOT NULL DEFAULT FALSE,
    status              TEXT NOT NULL DEFAULT 'draft'
                        CHECK (status IN (
                            'draft', 'sandbox', 'shadow', 'active',
                            'rolled_back', 'rejected'
                        )),
    model_card_path     TEXT,
    promoted_by         TEXT,
    ceo_decision_id     TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ln7_revisions_one_active
    ON ln7_revisions ((active)) WHERE active = TRUE;

CREATE TABLE IF NOT EXISTS ln7_tasks (
    task_id         TEXT PRIMARY KEY,
    source          TEXT NOT NULL
                    CHECK (source IN ('mined', 'mutation', 'public', 'authored', 'repo_mined', 'synthetic_bug', 'public_bench')),
    difficulty      TEXT DEFAULT 'medium',
    task_hash       TEXT NOT NULL,
    split           TEXT NOT NULL DEFAULT 'train'
                    CHECK (split IN ('train', 'heldout', 'eval')),
    spdx_license    TEXT,
    pack_name       TEXT,
    prompt_summary  TEXT,
    metadata_json   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ln7_tasks_split ON ln7_tasks (split);
CREATE INDEX IF NOT EXISTS idx_ln7_tasks_hash ON ln7_tasks (task_hash);

CREATE TABLE IF NOT EXISTS ln7_coding_outcomes (
    id              BIGSERIAL PRIMARY KEY,
    task_id         TEXT REFERENCES ln7_tasks(task_id),
    generator       TEXT NOT NULL,
    revision_id     TEXT REFERENCES ln7_revisions(revision_id),
    harness_mode    TEXT,
    patch_hash      TEXT,
    passed          BOOLEAN NOT NULL DEFAULT FALSE,
    tests_passed    INT,
    diff_lines      INT,
    tokens          INT,
    latency_ms      INT,
    cost_usd        NUMERIC(12, 6),
    recall_at_k     NUMERIC(6, 4),
    exec_node       TEXT DEFAULT 'green',
    metrics_json    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ln7_outcomes_rev ON ln7_coding_outcomes (revision_id);
CREATE INDEX IF NOT EXISTS idx_ln7_outcomes_gen ON ln7_coding_outcomes (generator, created_at DESC);

CREATE TABLE IF NOT EXISTS ln7_learning_artifacts (
    id              BIGSERIAL PRIMARY KEY,
    outcome_id      BIGINT REFERENCES ln7_coding_outcomes(id),
    path_or_r2_key  TEXT NOT NULL,
    summary         TEXT,
    crystal_id      TEXT,
    spdx_license    TEXT,
    task_hash       TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ln7_contestants (
    contestant_id       TEXT PRIMARY KEY,
    display_name        TEXT NOT NULL,
    provider            TEXT NOT NULL,
    base_url            TEXT,
    model_id            TEXT NOT NULL,
    version_captured_at TIMESTAMPTZ,
    enabled             BOOLEAN NOT NULL DEFAULT FALSE,
    metadata_json       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ln7_usage_event (
    id              BIGSERIAL PRIMARY KEY,
    event_type      TEXT NOT NULL
                    CHECK (event_type IN ('accepted', 'rejected', 'edited_after_apply')),
    patch_hash      TEXT,
    content_hash    TEXT,
    revision_id     TEXT,
    workspace_hint  TEXT,
    metadata_json   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed baseline revision (inactive until bakeoff promotes)
INSERT INTO ln7_revisions (
    revision_id, revised_at, base_checkpoint, quantization,
    harness_config_json, notes, active, status, model_card_path
) VALUES (
    'LN7-baseline',
    NOW(),
    'qwen2.5-coder:32b-instruct-q5_K_M',
    'q5_K_M',
    '{"best_of_n": 4, "mode": "max"}'::jsonb,
    'Day-0 stock coder weights baseline',
    TRUE,
    'active',
    'docs/ln7/LN7_baseline.md'
) ON CONFLICT (revision_id) DO NOTHING;

-- Seed contestant registry (disabled until credentials exist)
INSERT INTO ln7_contestants (contestant_id, display_name, provider, model_id, enabled)
VALUES
    ('foundry_grok', 'Foundry Grok', 'foundry', 'grok-4-1-fast-reasoning', FALSE),
    ('xai_grok', 'xAI Grok 4.5', 'xai', 'grok-4', FALSE),
    ('fable_5', 'Fable 5', 'fable', 'fable-5', FALSE),
    ('mythos_5', 'Mythos 5', 'mythos', 'mythos-5', FALSE)
ON CONFLICT (contestant_id) DO NOTHING;

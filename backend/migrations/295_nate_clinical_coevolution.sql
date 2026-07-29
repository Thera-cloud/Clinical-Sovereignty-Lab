-- QUANTUM-CRYSTAL-ARCH — Little Nate Competitive Clinical Coevolution (additive)
-- All feature flags default off in app code; this migration only creates tables.

CREATE TABLE IF NOT EXISTS nate_clinical_variants (
    variant_id TEXT PRIMARY KEY,
    prompt_pack TEXT NOT NULL DEFAULT '',
    prompt_pack_hash TEXT NOT NULL DEFAULT '',
    crystal_index_scope TEXT NOT NULL DEFAULT 'clinical_global',
    modality_router_on BOOLEAN NOT NULL DEFAULT FALSE,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS nate_clinical_seeds (
    seed_id TEXT PRIMARY KEY,
    seed_hash TEXT NOT NULL UNIQUE,
    split TEXT NOT NULL CHECK (split IN ('train', 'heldout')),
    curriculum_level INT NOT NULL DEFAULT 1 CHECK (curriculum_level BETWEEN 1 AND 3),
    persona_prompt_hash TEXT NOT NULL DEFAULT '',
    opening_line TEXT NOT NULL DEFAULT '',
    synthetic_ok BOOLEAN NOT NULL DEFAULT TRUE,
    reuse_count INT NOT NULL DEFAULT 0,
    max_reuse INT NOT NULL DEFAULT 3,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS nate_clinical_frozen_packs (
    frozen_context_hash TEXT PRIMARY KEY,
    snapshot_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    crystal_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    filters_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS nate_clinical_bakeoff_matches (
    match_id UUID PRIMARY KEY,
    seed_id TEXT REFERENCES nate_clinical_seeds(seed_id),
    curriculum_level INT NOT NULL DEFAULT 1,
    variant_a TEXT NOT NULL,
    variant_b TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'aborted'
        CHECK (status IN ('complete', 'aborted', 'gate_fail', 'preflight_fail')),
    winner TEXT CHECK (winner IS NULL OR winner IN ('a', 'b', 'tie')),
    judge_rationale_json JSONB,
    hard_gate_a BOOLEAN,
    hard_gate_b BOOLEAN,
    gate_outcome TEXT,
    turn_counts INT,
    token_counts_a INT,
    token_counts_b INT,
    prompt_pack_hash_a TEXT,
    prompt_pack_hash_b TEXT,
    nate_model_id TEXT,
    nate_temperature DOUBLE PRECISION,
    patient_sim_model_id TEXT,
    patient_sim_temp DOUBLE PRECISION,
    patient_persona_prompt_hash TEXT,
    frozen_context_hash TEXT REFERENCES nate_clinical_frozen_packs(frozen_context_hash),
    judge_model_id TEXT,
    judge_version_captured_at TIMESTAMPTZ,
    judge_order_concordant BOOLEAN,
    trajectory_a JSONB,
    trajectory_b JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_nate_clinical_matches_id
    ON nate_clinical_bakeoff_matches (match_id);

CREATE TABLE IF NOT EXISTS nate_clinical_preferences (
    id BIGSERIAL PRIMARY KEY,
    match_id UUID NOT NULL UNIQUE REFERENCES nate_clinical_bakeoff_matches(match_id),
    x JSONB NOT NULL,
    y_win TEXT NOT NULL,
    y_lose TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    split TEXT NOT NULL CHECK (split IN ('train', 'heldout')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS nate_clinical_lessons (
    id BIGSERIAL PRIMARY KEY,
    lesson_text TEXT NOT NULL,
    trigger_pattern TEXT NOT NULL DEFAULT '',
    source_match_id UUID,
    match_count INT NOT NULL DEFAULT 1,
    crystal_id TEXT,
    superseded_by BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS nate_patient_curriculum_state (
    id INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    level INT NOT NULL DEFAULT 1 CHECK (level BETWEEN 1 AND 3),
    win_rate_window DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    last_escalation_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO nate_patient_curriculum_state (id, level)
VALUES (1, 1)
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS nate_clinical_revisions (
    revision_id TEXT PRIMARY KEY,
    checkpoint_ref TEXT NOT NULL,
    provider TEXT NOT NULL CHECK (provider IN ('sovereign', 'home_gpu')),
    active BOOLEAN NOT NULL DEFAULT FALSE,
    supersedes TEXT,
    ceo_decision_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS nate_clinical_bakeoff_nightly_stats (
    night_bucket DATE PRIMARY KEY,
    matches_attempted INT NOT NULL DEFAULT 0,
    matches_complete INT NOT NULL DEFAULT 0,
    preferences_written INT NOT NULL DEFAULT 0,
    both_failed_gate INT NOT NULL DEFAULT 0,
    one_failed_gate INT NOT NULL DEFAULT 0,
    tie_or_discordant INT NOT NULL DEFAULT 0,
    judge_tokens_used INT NOT NULL DEFAULT 0,
    aborted_budget INT NOT NULL DEFAULT 0,
    order_swap_concordance DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Migration 142: Sovereign Standard CLI structures
-- Adds mode-aware source repair controls, artifacts, scoring, authority, and evaluation battery.

-- 1) Extend source_repair_requests lifecycle/governance columns
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='source_repair_requests' AND column_name='mode') THEN
        ALTER TABLE source_repair_requests ADD COLUMN mode TEXT NOT NULL DEFAULT 'debug';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='source_repair_requests' AND column_name='scope_hash') THEN
        ALTER TABLE source_repair_requests ADD COLUMN scope_hash TEXT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='source_repair_requests' AND column_name='approval_expires_at') THEN
        ALTER TABLE source_repair_requests ADD COLUMN approval_expires_at TIMESTAMPTZ;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='source_repair_requests' AND column_name='clinical_sign_off') THEN
        ALTER TABLE source_repair_requests ADD COLUMN clinical_sign_off BOOLEAN NOT NULL DEFAULT false;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='source_repair_requests' AND column_name='idempotency_key') THEN
        ALTER TABLE source_repair_requests ADD COLUMN idempotency_key TEXT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='source_repair_requests' AND column_name='rollback_procedure') THEN
        ALTER TABLE source_repair_requests ADD COLUMN rollback_procedure TEXT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='source_repair_requests' AND column_name='witnessing_cli') THEN
        ALTER TABLE source_repair_requests ADD COLUMN witnessing_cli TEXT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='source_repair_requests' AND column_name='witnessing_at') THEN
        ALTER TABLE source_repair_requests ADD COLUMN witnessing_at TIMESTAMPTZ;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='source_repair_requests' AND column_name='coherence_projection') THEN
        ALTER TABLE source_repair_requests ADD COLUMN coherence_projection JSONB NOT NULL DEFAULT '{}'::jsonb;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='source_repair_requests' AND column_name='coherence_assessment') THEN
        ALTER TABLE source_repair_requests ADD COLUMN coherence_assessment JSONB NOT NULL DEFAULT '{}'::jsonb;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='source_repair_requests' AND column_name='c_emo_before') THEN
        ALTER TABLE source_repair_requests ADD COLUMN c_emo_before DOUBLE PRECISION;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='source_repair_requests' AND column_name='c_emo_after') THEN
        ALTER TABLE source_repair_requests ADD COLUMN c_emo_after DOUBLE PRECISION;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='source_repair_requests' AND column_name='coherence_proxy_type') THEN
        ALTER TABLE source_repair_requests ADD COLUMN coherence_proxy_type TEXT NOT NULL DEFAULT 'system';
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_source_repair_mode ON source_repair_requests(mode);
CREATE INDEX IF NOT EXISTS idx_source_repair_idempotency_key ON source_repair_requests(idempotency_key) WHERE idempotency_key IS NOT NULL;

-- 2) cli_mode_runs
CREATE TABLE IF NOT EXISTS cli_mode_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id UUID REFERENCES source_repair_requests(id) ON DELETE CASCADE,
    cli_agent TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    scope_hash TEXT,
    rollback_procedure TEXT,
    coherence_projection JSONB NOT NULL DEFAULT '{}'::jsonb,
    coherence_assessment JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cli_mode_runs_agent_mode ON cli_mode_runs(cli_agent, mode);
CREATE INDEX IF NOT EXISTS idx_cli_mode_runs_status ON cli_mode_runs(status);

-- 3) cli_mode_artifacts
CREATE TABLE IF NOT EXISTS cli_mode_artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID REFERENCES cli_mode_runs(id) ON DELETE CASCADE,
    request_id UUID REFERENCES source_repair_requests(id) ON DELETE CASCADE,
    artifact_type TEXT NOT NULL,
    content_format TEXT NOT NULL DEFAULT 'text',
    content TEXT,
    r2_key TEXT,
    content_size_bytes BIGINT NOT NULL DEFAULT 0,
    version_hash TEXT NOT NULL,
    nevedal_impact JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cli_mode_artifacts_request ON cli_mode_artifacts(request_id);
CREATE INDEX IF NOT EXISTS idx_cli_mode_artifacts_r2_key ON cli_mode_artifacts(r2_key) WHERE r2_key IS NOT NULL;

-- 4) cli_mode_scores
CREATE TABLE IF NOT EXISTS cli_mode_scores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID REFERENCES cli_mode_runs(id) ON DELETE CASCADE,
    request_id UUID REFERENCES source_repair_requests(id) ON DELETE CASCADE,
    cli_agent TEXT NOT NULL,
    mode TEXT NOT NULL,
    rubric_version TEXT NOT NULL,
    scorer_identity TEXT NOT NULL,
    evaluation_context TEXT NOT NULL DEFAULT 'cold_no_memory',
    model_version TEXT,
    correctness DOUBLE PRECISION NOT NULL DEFAULT 0,
    safety DOUBLE PRECISION NOT NULL DEFAULT 0,
    reversibility DOUBLE PRECISION NOT NULL DEFAULT 0,
    clinical_reasoning DOUBLE PRECISION NOT NULL DEFAULT 0,
    confidence_calibration DOUBLE PRECISION NOT NULL DEFAULT 0,
    weighted_total DOUBLE PRECISION NOT NULL DEFAULT 0,
    projection_accuracy DOUBLE PRECISION NOT NULL DEFAULT 0,
    nevedal_ec_at_evaluation DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cli_mode_scores_agent ON cli_mode_scores(cli_agent, created_at DESC);

-- 5) ln_fab_memory_patterns
CREATE TABLE IF NOT EXISTS ln_fab_memory_patterns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_run_id UUID REFERENCES cli_mode_runs(id) ON DELETE SET NULL,
    pattern_text TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
    clinical_review_status TEXT NOT NULL DEFAULT 'pending',
    quarantine_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lnfab_memory_review_status ON ln_fab_memory_patterns(clinical_review_status);

-- 6) cli_authority_records
CREATE TABLE IF NOT EXISTS cli_authority_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cli_agent TEXT NOT NULL,
    domain TEXT NOT NULL,
    current_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    gate_level TEXT,
    last_evaluated_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (cli_agent, domain)
);

-- 7) coherence_impact_log
CREATE TABLE IF NOT EXISTS coherence_impact_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id UUID REFERENCES source_repair_requests(id) ON DELETE CASCADE,
    run_id UUID REFERENCES cli_mode_runs(id) ON DELETE SET NULL,
    c_emo_before DOUBLE PRECISION,
    c_emo_after DOUBLE PRECISION,
    violation_level TEXT,
    auto_rolled_back BOOLEAN NOT NULL DEFAULT false,
    coherence_proxy_type TEXT NOT NULL DEFAULT 'system',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_coherence_impact_request ON coherence_impact_log(request_id, created_at DESC);

-- 8) cli_conflict_resolutions
CREATE TABLE IF NOT EXISTS cli_conflict_resolutions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id_a UUID REFERENCES source_repair_requests(id) ON DELETE CASCADE,
    request_id_b UUID REFERENCES source_repair_requests(id) ON DELETE CASCADE,
    resolution_type TEXT NOT NULL,
    resolved_by TEXT NOT NULL,
    admin_note TEXT,
    resolved_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cli_conflict_resolved_at ON cli_conflict_resolutions(resolved_at DESC);

-- 9) cli_evaluation_battery
CREATE TABLE IF NOT EXISTS cli_evaluation_battery (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cli_agent TEXT NOT NULL,
    domain TEXT NOT NULL,
    difficulty TEXT NOT NULL DEFAULT 'standard',
    scenario_text TEXT NOT NULL,
    expected_behavior TEXT NOT NULL,
    cli_response TEXT,
    score DOUBLE PRECISION,
    rubric_version TEXT NOT NULL,
    scorer_identity TEXT NOT NULL,
    evaluation_context TEXT NOT NULL DEFAULT 'cold_no_memory',
    model_version TEXT,
    evaluated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cli_eval_agent_domain ON cli_evaluation_battery(cli_agent, domain);

-- =============================================================================
-- Migration 007: Strategic Memory — 6-Layer System
-- Sovereign Swarm Intelligence Framework
-- =============================================================================

-- ─── Layer 1: Standing Orders ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS standing_orders (
    id              SERIAL PRIMARY KEY,
    order_id        UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    title           VARCHAR(256) NOT NULL,
    directive       TEXT NOT NULL,
    origin          VARCHAR(64) NOT NULL DEFAULT 'big_nate_direct',
    domain_tags     TEXT[] DEFAULT '{}',
    priority        INTEGER NOT NULL DEFAULT 5 CHECK (priority BETWEEN 1 AND 10),
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    performance_score FLOAT,
    created_by      VARCHAR(64) NOT NULL DEFAULT 'big_nate',
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_standing_orders_active ON standing_orders(active) WHERE active = TRUE;
CREATE INDEX IF NOT EXISTS idx_standing_orders_domain ON standing_orders USING GIN(domain_tags);


-- ─── Layer 2: Insight Log ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS insight_log (
    id              SERIAL PRIMARY KEY,
    insight_id      UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    title           VARCHAR(256) NOT NULL,
    body            TEXT NOT NULL,
    domain          VARCHAR(64) NOT NULL DEFAULT 'operational',
    confidence      FLOAT NOT NULL DEFAULT 0.5 CHECK (confidence BETWEEN 0 AND 1),
    tags            TEXT[] DEFAULT '{}',
    source_fibre_id UUID,
    source_type     VARCHAR(32) NOT NULL DEFAULT 'system',
    related_insight_ids UUID[] DEFAULT '{}',
    promoted_to_order BOOLEAN NOT NULL DEFAULT FALSE,
    promoted_order_id UUID,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_insight_log_domain ON insight_log(domain);
CREATE INDEX IF NOT EXISTS idx_insight_log_confidence ON insight_log(confidence DESC);
CREATE INDEX IF NOT EXISTS idx_insight_log_tags ON insight_log USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_insight_log_created ON insight_log(created_at DESC);


-- ─── Layer 3: Strategy Proposals (Deploy Queue) ───────────────────────────
CREATE TABLE IF NOT EXISTS strategy_proposals (
    id              SERIAL PRIMARY KEY,
    proposal_id     UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    title           VARCHAR(256) NOT NULL,
    description     TEXT NOT NULL,
    action_type     VARCHAR(64) NOT NULL,
    proposed_by     VARCHAR(64) NOT NULL DEFAULT 'sovereign_mind',
    risk            VARCHAR(16) NOT NULL DEFAULT 'medium',
    status          VARCHAR(32) NOT NULL DEFAULT 'proposed',

    -- Execution
    execution_payload   JSONB DEFAULT '{}',
    rollback_payload    JSONB,
    auto_execute_after  TIMESTAMPTZ,

    -- Approval
    approved_by     VARCHAR(64),
    approved_at     TIMESTAMPTZ,
    rejection_reason TEXT,

    -- Results
    execution_result JSONB,
    executed_at     TIMESTAMPTZ,

    -- Metadata
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_proposals_status ON strategy_proposals(status);
CREATE INDEX IF NOT EXISTS idx_proposals_risk ON strategy_proposals(risk);
CREATE INDEX IF NOT EXISTS idx_proposals_auto_exec ON strategy_proposals(auto_execute_after)
    WHERE status = 'pending_approval' AND auto_execute_after IS NOT NULL;


-- ─── Layer 4: Coherence Briefings ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS coherence_briefings (
    id              SERIAL PRIMARY KEY,
    briefing_id     UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    period_start    TIMESTAMPTZ NOT NULL,
    period_end      TIMESTAMPTZ NOT NULL,
    global_coherence_index FLOAT DEFAULT 0 CHECK (global_coherence_index BETWEEN 0 AND 1),
    layer_summaries JSONB DEFAULT '{}',
    trending_themes TEXT[] DEFAULT '{}',
    gap_analysis_summary TEXT,
    notable_changes TEXT[] DEFAULT '{}',
    recommendations TEXT[] DEFAULT '{}',
    metadata        JSONB DEFAULT '{}',
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_coherence_briefings_generated ON coherence_briefings(generated_at DESC);


-- ─── Layer 5: Foresight Alerts ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS foresight_alerts (
    id              SERIAL PRIMARY KEY,
    alert_id        UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    signal_description TEXT NOT NULL,
    confidence      FLOAT NOT NULL DEFAULT 0.5 CHECK (confidence BETWEEN 0 AND 1),
    confidence_interval_lower FLOAT DEFAULT 0,
    confidence_interval_upper FLOAT DEFAULT 1,
    time_horizon_hours INTEGER DEFAULT 24,
    affected_populations TEXT[] DEFAULT '{}',
    recommended_actions TEXT[] DEFAULT '{}',
    alternative_scenarios JSONB DEFAULT '[]',
    monitoring_indicators TEXT[] DEFAULT '{}',
    source_fibre_id UUID,
    source_data_streams TEXT[] DEFAULT '{}',
    actual_outcome  TEXT,
    accuracy_score  FLOAT,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_foresight_active ON foresight_alerts(created_at DESC)
    WHERE resolved_at IS NULL;


-- ─── Layer 6: Swarm Oversight ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS swarm_oversight_log (
    id              SERIAL PRIMARY KEY,
    entry_id        UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    event_type      VARCHAR(32) NOT NULL,
    fibre_id        UUID,
    fibre_type      VARCHAR(32),
    details         JSONB DEFAULT '{}',
    mesh_health     JSONB,
    active_fibre_count INTEGER DEFAULT 0,
    total_tokens_consumed BIGINT DEFAULT 0,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_swarm_event_type ON swarm_oversight_log(event_type);
CREATE INDEX IF NOT EXISTS idx_swarm_fibre_id ON swarm_oversight_log(fibre_id);
CREATE INDEX IF NOT EXISTS idx_swarm_created ON swarm_oversight_log(created_at DESC);


-- ─── Coherence Measurements (shared by coherence_engine) ──────────────────
CREATE TABLE IF NOT EXISTS coherence_measurements (
    id              SERIAL PRIMARY KEY,
    measurement_id  UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    layer           VARCHAR(16) NOT NULL,
    score           FLOAT NOT NULL CHECK (score BETWEEN 0 AND 1),
    confidence      FLOAT DEFAULT 0.5 CHECK (confidence BETWEEN 0 AND 1),
    user_id         UUID REFERENCES users(id),
    family_id       UUID REFERENCES families(id),
    community_id    VARCHAR(64),
    cultural_context VARCHAR(128),
    region          VARCHAR(128),
    components      JSONB DEFAULT '{}',
    delta_24h       FLOAT,
    delta_7d        FLOAT,
    sample_size     INTEGER DEFAULT 0,
    metadata        JSONB DEFAULT '{}',
    measured_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_coherence_layer ON coherence_measurements(layer);
CREATE INDEX IF NOT EXISTS idx_coherence_user ON coherence_measurements(user_id);
CREATE INDEX IF NOT EXISTS idx_coherence_family ON coherence_measurements(family_id);
CREATE INDEX IF NOT EXISTS idx_coherence_measured ON coherence_measurements(measured_at DESC);

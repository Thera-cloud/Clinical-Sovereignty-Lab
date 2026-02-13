-- =============================================================================
-- Migration 008: Swarm Genesis — Fibre Architecture Tables
-- Sovereign Swarm Intelligence Framework — Phase 3G
-- =============================================================================

-- ─── Fibres (core state table) ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fibres (
    id              SERIAL PRIMARY KEY,
    fibre_id        UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    fibre_type      VARCHAR(32) NOT NULL,
    name            VARCHAR(128) NOT NULL,
    description     TEXT DEFAULT '',
    status          VARCHAR(16) NOT NULL DEFAULT 'initializing',
    autonomy_level  VARCHAR(16) NOT NULL DEFAULT 'observation',

    -- Identity
    public_key      TEXT,
    identity_signature TEXT,
    ethical_core_hash VARCHAR(64),

    -- Configuration
    domain_tags     TEXT[] DEFAULT '{}',
    token_budget_per_hour INTEGER DEFAULT 10000,
    max_concurrent_tasks INTEGER DEFAULT 3,
    wisdom_seed     JSONB DEFAULT '{}',
    parent_fibre_id UUID,

    -- Runtime
    tokens_used_this_hour INTEGER DEFAULT 0,
    last_active     TIMESTAMPTZ,
    alignment_ethical FLOAT DEFAULT 1.0,
    alignment_strategic FLOAT DEFAULT 1.0,
    alignment_statistical FLOAT DEFAULT 1.0,

    -- Wisdom
    evolution_journal_ref TEXT,
    wisdom_mesh_subscriptions TEXT[] DEFAULT '{}',

    -- Metadata
    config          JSONB DEFAULT '{}',
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fibres_status ON fibres(status);
CREATE INDEX IF NOT EXISTS idx_fibres_type ON fibres(fibre_type);
CREATE INDEX IF NOT EXISTS idx_fibres_active ON fibres(status, last_active DESC)
    WHERE status IN ('active', 'idle');
CREATE INDEX IF NOT EXISTS idx_fibres_parent ON fibres(parent_fibre_id);


-- ─── Fibre Evolution Journal ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fibre_evolution_journal (
    id              SERIAL PRIMARY KEY,
    entry_id        UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    fibre_id        UUID NOT NULL REFERENCES fibres(fibre_id) ON DELETE CASCADE,
    task_id         UUID,
    task_type       VARCHAR(64),
    success         BOOLEAN,
    tokens_used     INTEGER DEFAULT 0,
    duration_ms     INTEGER DEFAULT 0,
    ethical_compliance FLOAT DEFAULT 1.0,
    alignment_scores JSONB DEFAULT '{}',
    output_summary  TEXT,
    event_type      VARCHAR(32) DEFAULT 'task',
    details         JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_journal_fibre ON fibre_evolution_journal(fibre_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_journal_task ON fibre_evolution_journal(task_id);


-- ─── Wisdom Mesh Messages (audit/replay log) ─────────────────────────────
CREATE TABLE IF NOT EXISTS wisdom_mesh_messages (
    id              SERIAL PRIMARY KEY,
    message_id      UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    message_type    VARCHAR(32) NOT NULL,
    priority        VARCHAR(16) NOT NULL DEFAULT 'normal',
    sender_id       UUID NOT NULL,
    sender_type     VARCHAR(16) DEFAULT 'fibre',
    recipient_id    UUID,
    domain_tags     TEXT[] DEFAULT '{}',
    topology_level  VARCHAR(16) DEFAULT 'level_2',
    subject         TEXT DEFAULT '',
    body            JSONB DEFAULT '{}',
    signature       TEXT,
    identity_chain  TEXT[],
    ttl_seconds     INTEGER DEFAULT 3600,
    delivered_at    TIMESTAMPTZ,
    acknowledged_at TIMESTAMPTZ,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mesh_sender ON wisdom_mesh_messages(sender_id);
CREATE INDEX IF NOT EXISTS idx_mesh_recipient ON wisdom_mesh_messages(recipient_id);
CREATE INDEX IF NOT EXISTS idx_mesh_type ON wisdom_mesh_messages(message_type);
CREATE INDEX IF NOT EXISTS idx_mesh_domain ON wisdom_mesh_messages USING GIN(domain_tags);
CREATE INDEX IF NOT EXISTS idx_mesh_created ON wisdom_mesh_messages(created_at DESC);


-- ─── Convergence Alerts ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS convergence_alerts (
    id              SERIAL PRIMARY KEY,
    alert_id        UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    converging_fibre_ids UUID[] DEFAULT '{}',
    converging_message_ids UUID[] DEFAULT '{}',
    topic           TEXT NOT NULL,
    convergence_score FLOAT NOT NULL CHECK (convergence_score BETWEEN 0 AND 1),
    temporal_correlation FLOAT DEFAULT 0,
    synthesis       TEXT DEFAULT '',
    domain_tags     TEXT[] DEFAULT '{}',
    promoted_to_insight BOOLEAN DEFAULT FALSE,
    insight_id      UUID,
    metadata        JSONB DEFAULT '{}',
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_convergence_detected ON convergence_alerts(detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_convergence_topic ON convergence_alerts(topic);


-- ─── Ethical Audit Log ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ethical_audit_log (
    id              SERIAL PRIMARY KEY,
    audit_id        UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    fibre_id        UUID REFERENCES fibres(fibre_id) ON DELETE SET NULL,
    check_type      VARCHAR(32) NOT NULL,
    passed          BOOLEAN NOT NULL,
    scores          JSONB DEFAULT '{}',
    details         TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ethical_audit_fibre ON ethical_audit_log(fibre_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ethical_audit_failed ON ethical_audit_log(created_at DESC)
    WHERE passed = FALSE;


-- ─── Quarantine Log ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS quarantine_log (
    id              SERIAL PRIMARY KEY,
    quarantine_id   UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    fibre_id        UUID REFERENCES fibres(fibre_id) ON DELETE SET NULL,
    reason          TEXT NOT NULL,
    triggered_by    VARCHAR(64) NOT NULL DEFAULT 'sovereign_immunity',
    severity        VARCHAR(16) NOT NULL DEFAULT 'medium',
    forensic_data   JSONB DEFAULT '{}',
    resolved        BOOLEAN DEFAULT FALSE,
    resolved_at     TIMESTAMPTZ,
    resolution      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quarantine_fibre ON quarantine_log(fibre_id);
CREATE INDEX IF NOT EXISTS idx_quarantine_unresolved ON quarantine_log(created_at DESC)
    WHERE resolved = FALSE;

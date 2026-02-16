-- ============================================================================
-- Migration 023: Sovereign Mind Tables
-- Layer 2 — Command & Control
-- Patent Claims 1, 3, 11, 18, 21, 22
-- ============================================================================

-- Directives — commands from Sovereign Mind to Fibres
CREATE TABLE IF NOT EXISTS sovereign_directives (
    directive_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    issued_at           TIMESTAMPTZ DEFAULT NOW(),
    issued_by           VARCHAR(64) DEFAULT 'sovereign_mind',
    target_fibre_ids    TEXT[] DEFAULT '{}',
    target_fibre_types  TEXT[] DEFAULT '{}',
    directive_type      VARCHAR(32) NOT NULL
        CHECK (directive_type IN ('standing_order', 'mission_update',
                                   'priority_shift', 'recall', 'spawn',
                                   'dissolve', 'reform')),
    content             JSONB NOT NULL DEFAULT '{}',
    priority            VARCHAR(12) DEFAULT 'normal'
        CHECK (priority IN ('low', 'normal', 'high', 'critical')),
    expires_at          TIMESTAMPTZ,
    acknowledged_by     TEXT[] DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_directives_type
    ON sovereign_directives (directive_type, issued_at DESC);
CREATE INDEX IF NOT EXISTS idx_directives_priority
    ON sovereign_directives (priority, issued_at DESC)
    WHERE priority IN ('high', 'critical');

-- Wisdom absorptions — Fibre insights absorbed by Sovereign Mind
CREATE TABLE IF NOT EXISTS wisdom_absorptions (
    id                  BIGSERIAL PRIMARY KEY,
    fibre_id            VARCHAR(128) NOT NULL,
    fibre_type          VARCHAR(32),
    absorbed_at         TIMESTAMPTZ DEFAULT NOW(),
    wisdom_type         VARCHAR(32) DEFAULT 'insight',
    content_summary     TEXT,
    domain_tags         TEXT[] DEFAULT '{}',
    confidence          REAL DEFAULT 0.5,
    convergence_detected BOOLEAN DEFAULT FALSE,
    convergence_score   REAL,
    contributing_fibres TEXT[] DEFAULT '{}',
    escalated           BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_absorptions_fibre
    ON wisdom_absorptions (fibre_id, absorbed_at DESC);
CREATE INDEX IF NOT EXISTS idx_absorptions_convergence
    ON wisdom_absorptions (convergence_detected, absorbed_at DESC)
    WHERE convergence_detected = TRUE;

-- Cross-domain syntheses — emergent insights from multiple Fibre domains
CREATE TABLE IF NOT EXISTS cross_domain_syntheses (
    id                      BIGSERIAL PRIMARY KEY,
    synthesized_at          TIMESTAMPTZ DEFAULT NOW(),
    domains                 TEXT[] NOT NULL DEFAULT '{}',
    contributing_fibre_ids  TEXT[] DEFAULT '{}',
    contributing_fibre_types TEXT[] DEFAULT '{}',
    convergence_themes      JSONB DEFAULT '[]',
    synthesis_report        JSONB DEFAULT '{}',
    confidence              REAL DEFAULT 0.5,
    action_items            JSONB DEFAULT '[]',
    human_reviewed          BOOLEAN DEFAULT FALSE,
    reviewed_at             TIMESTAMPTZ,
    reviewed_by             VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS idx_syntheses_domains
    ON cross_domain_syntheses USING GIN (domains);

-- Big Nate chat sessions — conversation history for auditing
CREATE TABLE IF NOT EXISTS big_nate_sessions (
    session_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    ended_at        TIMESTAMPTZ,
    operator_id     VARCHAR(64),
    mode            VARCHAR(20) DEFAULT 'briefing'
        CHECK (mode IN ('briefing', 'strategy', 'command', 'inquiry', 'swarm')),
    messages        JSONB DEFAULT '[]',
    summary         TEXT,
    directives_issued INTEGER DEFAULT 0,
    proposals_created INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_bignate_sessions_operator
    ON big_nate_sessions (operator_id, started_at DESC);

-- Spawn evaluations — records of Fibre spawn decisions
CREATE TABLE IF NOT EXISTS spawn_evaluations (
    id                  BIGSERIAL PRIMARY KEY,
    evaluated_at        TIMESTAMPTZ DEFAULT NOW(),
    requested_type      VARCHAR(32) NOT NULL,
    justification       TEXT,
    domain              VARCHAR(64),
    should_spawn        BOOLEAN NOT NULL,
    reasoning           TEXT,
    config_suggestion   JSONB DEFAULT '{}',
    executed            BOOLEAN DEFAULT FALSE,
    spawned_fibre_id    UUID
);

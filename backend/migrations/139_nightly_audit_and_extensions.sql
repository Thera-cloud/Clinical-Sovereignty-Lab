-- Migration 139: Combined — Nightly Audit + Nate Creative Extension System
-- Covers: Self-Healing Nightly Audit, Innovation Proposals, Extension Registry, Corporate Audit Account

-- ── Nightly Audit Results ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS nightly_audit_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_date DATE NOT NULL,
    phase INTEGER NOT NULL,
    phase_name VARCHAR(100) NOT NULL,
    test_name VARCHAR(200) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    detail TEXT,
    duration_ms INTEGER,
    run_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT valid_audit_status CHECK (status IN ('PASS', 'FAIL', 'SKIP', 'PENDING', 'ERROR'))
);

CREATE INDEX idx_nightly_audit_date ON nightly_audit_results(run_date DESC);
CREATE INDEX idx_nightly_audit_status ON nightly_audit_results(status) WHERE status != 'PASS';

-- ── Innovation Proposals (Executive Reports from Domain Agents / CLIs) ──
CREATE TABLE IF NOT EXISTS innovation_proposals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    proposed_by TEXT NOT NULL,
    extension_type TEXT NOT NULL,
    domain TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    executive_summary TEXT NOT NULL,
    problem_statement TEXT NOT NULL,
    proposed_solution JSONB NOT NULL,
    system_impact JSONB NOT NULL,
    downtime_estimate TEXT NOT NULL DEFAULT 'zero',
    cost_analysis JSONB NOT NULL DEFAULT '{}',
    performance_projections JSONB NOT NULL DEFAULT '{}',
    security_assessment JSONB NOT NULL DEFAULT '{}',
    rollback_plan TEXT NOT NULL,
    dependencies JSONB NOT NULL DEFAULT '[]',
    success_criteria JSONB NOT NULL DEFAULT '[]',
    cross_cli_coordination TEXT,
    admin_note TEXT,
    decided_by TEXT,
    decided_at TIMESTAMPTZ,
    executed_at TIMESTAMPTZ,
    execution_result JSONB,
    proposed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT valid_extension_type CHECK (extension_type IN ('formula', 'table', 'widget', 'webhook')),
    CONSTRAINT valid_proposal_status CHECK (status IN ('pending', 'approved', 'rejected', 'executed', 'failed', 'rolled_back'))
);

CREATE INDEX idx_innovation_proposals_status ON innovation_proposals(status);
CREATE INDEX idx_innovation_proposals_domain ON innovation_proposals(domain);
CREATE INDEX idx_innovation_proposals_by ON innovation_proposals(proposed_by, proposed_at DESC);

-- ── Nate Extensions (Active Extension Registry) ──
CREATE TABLE IF NOT EXISTS nate_extensions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    innovation_proposal_id UUID NOT NULL REFERENCES innovation_proposals(id),
    extension_type TEXT NOT NULL,
    domain TEXT NOT NULL,
    name TEXT NOT NULL,
    definition JSONB NOT NULL,
    d1_table_name TEXT,
    active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deactivated_at TIMESTAMPTZ,
    CONSTRAINT unique_extension_name UNIQUE (extension_type, name)
);

CREATE INDEX idx_extensions_active ON nate_extensions(active) WHERE active = true;
CREATE INDEX idx_extensions_type ON nate_extensions(extension_type);

-- ── Audit Corporate Client Test Account ──
INSERT INTO users (username, role, subscription_status, tier, hardware_id, password_hash, name, profile_data)
SELECT 'audit_corporate_client', 'CLIENT', 'ACTIVE', 'STANDARD',
       'AUDIT_CORPORATE_CLIENT_ID',
       '0000000000000000000000000000000000000000000000000000000000000000:0000000000000000000000000000000000000000000000000000000000000000',
       'Audit Corporate Client',
       jsonb_build_object(
           'name', 'Audit Corporate Client',
           'email', 'audit_corporate@sovereignsanctuary.net',
           'company_id', '00000000-0000-0000-0000-000000000099',
           'company_name', 'Audit Test Corp',
           'coach_id', 'COACH_COACHN_ID',
           'assigned_coach', 'CoachN',
           'assigned_coach_id', 'COACH_COACHN_ID',
           'consent_version', 'v13.0_2026'
       )
WHERE NOT EXISTS (SELECT 1 FROM users WHERE username = 'audit_corporate_client');

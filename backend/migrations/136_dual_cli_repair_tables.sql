-- Migration 136: Dual-CLI repair and approval tables (Dual-CLI Unified Master Plan)
-- Tables: repair_proposals (operational), autonomous_executions, source_repair_requests, approval_decisions (shared)

-- approval_decisions: shared connective tissue; created first so repair_proposals can FK it when decided
CREATE TABLE IF NOT EXISTS approval_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repair_proposal_id UUID NULL,
    source_repair_request_id UUID NULL,
    approved BOOLEAN NOT NULL,
    decided_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_by TEXT NOT NULL,
    admin_note TEXT NULL,
    CONSTRAINT approval_exactly_one_ref CHECK (
        (repair_proposal_id IS NOT NULL AND source_repair_request_id IS NULL)
        OR (repair_proposal_id IS NULL AND source_repair_request_id IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_approval_decisions_repair_proposal ON approval_decisions(repair_proposal_id) WHERE repair_proposal_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_approval_decisions_source_repair ON approval_decisions(source_repair_request_id) WHERE source_repair_request_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_approval_decisions_decided_at ON approval_decisions(decided_at);

-- repair_proposals: operational repairs (tunnel, KV, LB, VRAM, compliance, etc.)
CREATE TABLE IF NOT EXISTS repair_proposals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    proposed_by TEXT NOT NULL,
    repair_type TEXT NOT NULL,
    description TEXT NOT NULL,
    proposed_action TEXT NOT NULL,
    target TEXT NULL,
    autonomous BOOLEAN NOT NULL DEFAULT false,
    reversible BOOLEAN NOT NULL DEFAULT true,
    urgency TEXT NOT NULL DEFAULT 'review',
    status TEXT NOT NULL DEFAULT 'pending',
    admin_note TEXT NULL,
    proposed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_at TIMESTAMPTZ NULL,
    executed_at TIMESTAMPTZ NULL,
    execution_result JSONB NULL,
    cost_flag BOOLEAN NOT NULL DEFAULT false,
    conflicts_with UUID NULL REFERENCES repair_proposals(id),
    conflict_reason TEXT NULL,
    approval_decision_id UUID NULL REFERENCES approval_decisions(id)
);

-- Add cost_flag if table already exists (idempotent)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'repair_proposals' AND column_name = 'cost_flag') THEN
        ALTER TABLE repair_proposals ADD COLUMN cost_flag BOOLEAN NOT NULL DEFAULT false;
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_repair_proposals_status ON repair_proposals(status);
CREATE INDEX IF NOT EXISTS idx_repair_proposals_proposed_by ON repair_proposals(proposed_by);
CREATE INDEX IF NOT EXISTS idx_repair_proposals_proposed_at ON repair_proposals(proposed_at);
CREATE INDEX IF NOT EXISTS idx_repair_proposals_target ON repair_proposals(target);

-- autonomous_executions: log of pre-approved autonomous actions
CREATE TABLE IF NOT EXISTS autonomous_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cli_agent TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    before_state JSONB NULL,
    after_state JSONB NULL,
    executed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reversed_at TIMESTAMPTZ NULL,
    outcome TEXT NULL,
    approval_decision_id UUID NULL REFERENCES approval_decisions(id)
);
CREATE INDEX IF NOT EXISTS idx_autonomous_executions_cli_agent ON autonomous_executions(cli_agent);
CREATE INDEX IF NOT EXISTS idx_autonomous_executions_executed_at ON autonomous_executions(executed_at);

-- source_repair_requests: source-code repair flow (cross-CLI, admin-authorized)
CREATE TABLE IF NOT EXISTS source_repair_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    requester_cli TEXT NOT NULL,
    executor_cli TEXT NOT NULL,
    target TEXT NOT NULL,
    scope TEXT NULL,
    plan TEXT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    completion_report TEXT NULL,
    combined_report TEXT NULL,
    build_id TEXT NULL,
    parent_build_id TEXT NULL,
    proposed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_at TIMESTAMPTZ NULL,
    executed_at TIMESTAMPTZ NULL
);
CREATE INDEX IF NOT EXISTS idx_source_repair_requests_executor ON source_repair_requests(executor_cli);
CREATE INDEX IF NOT EXISTS idx_source_repair_requests_requester ON source_repair_requests(requester_cli);
CREATE INDEX IF NOT EXISTS idx_source_repair_requests_status ON source_repair_requests(status);
CREATE INDEX IF NOT EXISTS idx_source_repair_requests_proposed_at ON source_repair_requests(proposed_at);
CREATE INDEX IF NOT EXISTS idx_source_repair_requests_build_id ON source_repair_requests(build_id) WHERE build_id IS NOT NULL;

-- Add FKs from approval_decisions to repair_proposals and source_repair_requests (tables now exist)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_approval_repair_proposal') THEN
        ALTER TABLE approval_decisions
            ADD CONSTRAINT fk_approval_repair_proposal
                FOREIGN KEY (repair_proposal_id) REFERENCES repair_proposals(id) ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_approval_source_repair') THEN
        ALTER TABLE approval_decisions
            ADD CONSTRAINT fk_approval_source_repair
                FOREIGN KEY (source_repair_request_id) REFERENCES source_repair_requests(id) ON DELETE RESTRICT;
    END IF;
END $$;

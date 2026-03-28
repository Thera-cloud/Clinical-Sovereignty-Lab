-- Migration 138: CLI search approval flow + source_repair_requests concurrency columns
-- Supports: internet search CLI-to-CLI approval, backup restore gating, approval_decision_id FK

-- cli_search_requests: CLI-to-CLI internet search approval flow
CREATE TABLE IF NOT EXISTS cli_search_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    requester_cli TEXT NOT NULL,
    approver_cli TEXT NOT NULL,
    query TEXT NOT NULL,
    reason TEXT NOT NULL,
    context TEXT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    results TEXT NULL,
    approved_citations JSONB NULL,
    approver_note TEXT NULL,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL
);
CREATE INDEX IF NOT EXISTS idx_cli_search_requests_status ON cli_search_requests(status);
CREATE INDEX IF NOT EXISTS idx_cli_search_requests_approver ON cli_search_requests(approver_cli, status);
CREATE INDEX IF NOT EXISTS idx_cli_search_requests_requested_at ON cli_search_requests(requested_at);

-- Add approval_decision_id FK to source_repair_requests (Gap 5)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'source_repair_requests' AND column_name = 'approval_decision_id') THEN
        ALTER TABLE source_repair_requests ADD COLUMN approval_decision_id UUID NULL;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_source_repair_approval_decision') THEN
        ALTER TABLE source_repair_requests
            ADD CONSTRAINT fk_source_repair_approval_decision
                FOREIGN KEY (approval_decision_id) REFERENCES approval_decisions(id) ON DELETE SET NULL;
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_source_repair_approval_decision ON source_repair_requests(approval_decision_id) WHERE approval_decision_id IS NOT NULL;

-- Trust baseline for CLI auditor (14 checks across 5 tabs)
INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES ('cli_check_count', '{"expected": 14, "description": "CLI Agent Pipeline: 2 health + 4 proposal/source + 3 blob/backup + 3 search/read + 2 DB integrity"}'::jsonb)
ON CONFLICT (parameter_key) DO UPDATE SET parameter_value = EXCLUDED.parameter_value;

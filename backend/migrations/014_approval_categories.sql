-- ============================================================================
-- Migration 014: Approval Protocol — Category System Columns
-- Adds the 4-category approval system columns to strategy_proposals
-- (OBSERVE / SUGGEST / ACT / CRITICAL) per PhD Architecture Section 7.3.
-- ============================================================================

-- Add approval_category column (defaults to 'act' for backward compatibility)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'strategy_proposals' AND column_name = 'approval_category') THEN
        ALTER TABLE strategy_proposals
            ADD COLUMN approval_category VARCHAR(16) NOT NULL DEFAULT 'act';
    END IF;
END $$;

-- Add required_approvers column (for CRITICAL multi-party approval)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'strategy_proposals' AND column_name = 'required_approvers') THEN
        ALTER TABLE strategy_proposals
            ADD COLUMN required_approvers INTEGER NOT NULL DEFAULT 1;
    END IF;
END $$;

-- Add cooling_period_hours column (mandatory wait after CRITICAL approval)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'strategy_proposals' AND column_name = 'cooling_period_hours') THEN
        ALTER TABLE strategy_proposals
            ADD COLUMN cooling_period_hours INTEGER NOT NULL DEFAULT 0;
    END IF;
END $$;

-- Index for finding proposals by category
CREATE INDEX IF NOT EXISTS idx_strategy_proposals_category
    ON strategy_proposals(approval_category)
    WHERE status IN ('proposed', 'pending_approval');

-- Update existing proposals: classify based on risk level
UPDATE strategy_proposals
SET approval_category = CASE
    WHEN risk = 'low' THEN 'suggest'
    WHEN risk = 'medium' THEN 'act'
    WHEN risk = 'high' THEN 'act'
    WHEN risk = 'critical' THEN 'critical'
    ELSE 'act'
END
WHERE approval_category = 'act';

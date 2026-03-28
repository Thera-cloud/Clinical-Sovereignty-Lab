-- Migration 141: CLI source-repair lifecycle timestamps
-- Adds explicit execution start timestamp so UI can render:
-- pending_approval/draft -> approved -> executing (progress) -> completed (duration)

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'source_repair_requests'
          AND column_name = 'execution_started_at'
    ) THEN
        ALTER TABLE source_repair_requests
            ADD COLUMN execution_started_at TIMESTAMPTZ NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_source_repair_execution_started_at
    ON source_repair_requests(execution_started_at)
    WHERE execution_started_at IS NOT NULL;


-- Add RBAC + Crisis audit fields to cli_tool_calls
ALTER TABLE cli_tool_calls 
ADD COLUMN IF NOT EXISTS role_tier VARCHAR(50) NOT NULL DEFAULT 'admin',
ADD COLUMN IF NOT EXISTS data_classification VARCHAR(50),
ADD COLUMN IF NOT EXISTS args_redacted JSONB,
ADD COLUMN IF NOT EXISTS crisis_level VARCHAR(50),
ADD COLUMN IF NOT EXISTS crisis_crystallized BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS trajectory_id UUID;

-- Crisis trajectory persistence
CREATE TABLE IF NOT EXISTS cli_crisis_trajectories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id VARCHAR(255) NOT NULL,
    trajectory_json JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cli_crisis_trajectories_session ON cli_crisis_trajectories(session_id);

-- Role tier enum for consistency
CREATE TYPE user_role_tier AS ENUM ('admin', 'supervisor', 'enterprise', 'coach', 'client');

-- Backfill existing records
UPDATE cli_tool_calls SET role_tier = 'admin' WHERE role_tier IS NULL;

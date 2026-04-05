-- RBAC + Crisis Engine Integration
-- Migration 145

BEGIN;

-- User Roles
CREATE TABLE IF NOT EXISTS user_roles (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'coach', 'admin', 'system')),
    role_tier INTEGER DEFAULT 1 CHECK (role_tier BETWEEN 1 AND 4),
    assigned_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    UNIQUE(user_id, role)
);
CREATE INDEX IF NOT EXISTS ix_user_roles_user_id_role ON user_roles(user_id, role);

-- Crisis Trajectories
CREATE TABLE IF NOT EXISTS crisis_trajectories (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    user_role_id INTEGER NOT NULL REFERENCES user_roles(id) ON DELETE CASCADE,
    crisis_level VARCHAR(20) DEFAULT 'none' CHECK (crisis_level IN ('none', 'low', 'medium', 'high', 'critical')),
    trajectory_score DOUBLE PRECISION DEFAULT 0.0,
    last_assessed TIMESTAMPTZ DEFAULT NOW(),
    context_hash VARCHAR(64),
    mitigation_applied BOOLEAN DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS ix_crisis_trajectories_user_id_level ON crisis_trajectories(user_id, crisis_level);

-- Tool Audit Logs
CREATE TABLE IF NOT EXISTS tool_audit_logs (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    user_role_id INTEGER NOT NULL REFERENCES user_roles(id) ON DELETE SET NULL,
    tool_name VARCHAR(255) NOT NULL,
    tool_args JSONB,
    crisis_level VARCHAR(20) DEFAULT 'none' CHECK (crisis_level IN ('none', 'low', 'medium', 'high', 'critical')),
    role_tier INTEGER NOT NULL,
    risk_score DOUBLE PRECISION DEFAULT 0.0,
    approved BOOLEAN DEFAULT TRUE,
    executed_at TIMESTAMPTZ DEFAULT NOW(),
    session_id UUID
);
CREATE INDEX IF NOT EXISTS ix_tool_audit_logs_user_tool_executed ON tool_audit_logs(user_id, tool_name, executed_at);

-- Default system role for bridge
INSERT INTO user_roles (user_id, role, role_tier) 
VALUES ('system-bridge', 'system', 4)
ON CONFLICT (user_id, role) DO NOTHING;

COMMIT;

-- Post-migration verification
\echo 'RBAC + Crisis migration complete. Verify:';
SELECT COUNT(*) as role_count FROM user_roles;
SELECT COUNT(*) as trajectory_count FROM crisis_trajectories;
SELECT COUNT(*) as audit_count FROM tool_audit_logs;
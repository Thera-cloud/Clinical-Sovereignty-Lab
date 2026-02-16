-- =============================================================================
-- Migration 038: Organization Sessions for Nate Organizer
-- Persistent session state for AI-guided content organization
-- =============================================================================

CREATE TABLE IF NOT EXISTS organization_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id VARCHAR(255) NOT NULL,
    vault_item_id UUID,
    original_content TEXT NOT NULL,
    current_sections JSONB NOT NULL DEFAULT '[]',
    change_history JSONB NOT NULL DEFAULT '[]',
    status VARCHAR(20) DEFAULT 'active',  -- active, paused, completed, abandoned
    focus_thread VARCHAR(255),  -- current thread user is working on (ADHD support)
    progress_summary TEXT,  -- "4 of 7 sections organized"
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_org_sessions_member
    ON organization_sessions(member_id, status);

CREATE INDEX IF NOT EXISTS idx_org_sessions_vault_item
    ON organization_sessions(vault_item_id)
    WHERE vault_item_id IS NOT NULL;

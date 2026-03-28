-- Migration 159: LIMINAL RESOLVE protocol tables
-- Supports the 10-task non-linear therapeutic protocol with IFS parts detection,
-- shame topology tracking, connection-gated transitions, and LN Curiosity Registry.

CREATE TABLE IF NOT EXISTS liminal_resolve_states (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    surface TEXT DEFAULT 'chat',
    current_task INT DEFAULT 1,
    task_history JSONB DEFAULT '[]'::jsonb,
    cycle_count INT DEFAULT 0,
    session_count INT DEFAULT 0,
    curiosity_thread_notes TEXT,
    connection_vector JSONB DEFAULT '{}'::jsonb,
    parts_map JSONB DEFAULT '{}'::jsonb,
    shame_topology JSONB DEFAULT '{}'::jsonb,
    self_curiosity_score FLOAT DEFAULT 0.5,
    resolution_request_count INT DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT lr_status_check CHECK (status IN (
        'active',
        'carried_forward',
        'deactivated_curiosity',
        'deactivated_pattern_known',
        'deactivated_client_requested'
    ))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_lr_one_active_per_user
    ON liminal_resolve_states(user_id)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_lr_user_status
    ON liminal_resolve_states(user_id, status);

CREATE TABLE IF NOT EXISTS liminal_curiosity_registry (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question TEXT NOT NULL,
    domain TEXT DEFAULT 'general',
    related_crystal_ids JSONB DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'active',
    resolved_by_crystal_id UUID,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_curiosity_status
    ON liminal_curiosity_registry(status);

CREATE TABLE IF NOT EXISTS parts_detection_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id TEXT,
    turn_index INT,
    user_text TEXT,
    detected_parts JSONB,
    clinician_corrected_parts JSONB,
    correction_notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_crystal_liminal_domain
    ON nate_intelligence_crystals(domain)
    WHERE domain = 'liminal_resolve';

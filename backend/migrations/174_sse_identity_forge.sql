-- =============================================================================
-- Migration 174: SSE Identity Forge
-- Stores structured identity data extracted from the 10-turn intake
-- conversation. One row per user (UNIQUE on user_id).
-- =============================================================================

CREATE TABLE IF NOT EXISTS sse_identity_forge (
    forge_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL UNIQUE,
    character_visual TEXT,
    cultural_context TEXT,
    spiritual_framework TEXT,
    archetype_hint TEXT,
    presenting_concern TEXT,
    wound_indicator TEXT,
    strength_indicator TEXT,
    recommended_storyboard TEXT,
    clinical_eligibility_estimate FLOAT,
    safety_flags JSONB DEFAULT '[]',
    language_notes TEXT,
    conversation_history JSONB,
    status TEXT DEFAULT 'in_progress',
    created_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_sse_identity_forge_user
    ON sse_identity_forge (user_id);

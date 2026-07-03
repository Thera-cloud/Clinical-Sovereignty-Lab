-- Migration 231: Training Ground — Inner Leadership Mapping (additive)
-- user_id columns store users.username (canonical identity)

CREATE TABLE IF NOT EXISTS training_ground_consent (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
    consent_version TEXT NOT NULL,
    acknowledged_non_clinical BOOLEAN NOT NULL DEFAULT FALSE,
    acknowledged_coach_visibility BOOLEAN NOT NULL DEFAULT FALSE,
    acknowledged_persistence BOOLEAN NOT NULL DEFAULT FALSE,
    consented_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at TIMESTAMPTZ,
    UNIQUE (user_id, consent_version)
);
CREATE INDEX IF NOT EXISTS idx_training_ground_consent_user
    ON training_ground_consent (user_id, consented_at DESC);

ALTER TABLE user_parts_registry
    ADD COLUMN IF NOT EXISTS ilm_archetype_base VARCHAR(32),
    ADD COLUMN IF NOT EXISTS ifs_role VARCHAR(20),
    ADD COLUMN IF NOT EXISTS thera_world_template_id VARCHAR(64),
    ADD COLUMN IF NOT EXISTS activation_score SMALLINT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS coaching_status VARCHAR(24) DEFAULT 'APPROVED',
    ADD COLUMN IF NOT EXISTS coaching_status_notes TEXT,
    ADD COLUMN IF NOT EXISTS origin VARCHAR(24) DEFAULT 'sensitive_bridge';

CREATE INDEX IF NOT EXISTS idx_parts_registry_origin
    ON user_parts_registry (user_id, origin) WHERE is_active = TRUE;

CREATE TABLE IF NOT EXISTS user_part_relationships (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
    source_part_id INTEGER NOT NULL REFERENCES user_parts_registry(id) ON DELETE CASCADE,
    target_part_id INTEGER NOT NULL REFERENCES user_parts_registry(id) ON DELETE CASCADE,
    relationship_type VARCHAR(32) NOT NULL,
    conflict_intensity SMALLINT NOT NULL DEFAULT 0 CHECK (conflict_intensity BETWEEN 0 AND 10),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, source_part_id, target_part_id, relationship_type)
);
CREATE INDEX IF NOT EXISTS idx_user_part_relationships_user
    ON user_part_relationships (user_id);

CREATE TABLE IF NOT EXISTS training_ground_session (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
    state TEXT NOT NULL DEFAULT 'CONSENT',
    exercise_mode TEXT,
    council_snapshot JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_training_ground_session_user
    ON training_ground_session (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_training_ground_session_state
    ON training_ground_session (state) WHERE closed_at IS NULL;

CREATE TABLE IF NOT EXISTS training_ground_event (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES training_ground_session(id) ON DELETE SET NULL,
    user_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_training_ground_event_session
    ON training_ground_event (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_training_ground_event_type
    ON training_ground_event (event_type, created_at DESC);

CREATE TABLE IF NOT EXISTS training_ground_progression_tickets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES training_ground_session(id) ON DELETE SET NULL,
    user_id TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
    ticket_tier VARCHAR(16) NOT NULL,
    priority SMALLINT NOT NULL DEFAULT 3,
    auto_generated BOOLEAN NOT NULL DEFAULT TRUE,
    status VARCHAR(16) NOT NULL DEFAULT 'open',
    origin VARCHAR(24) NOT NULL DEFAULT 'training_ground',
    trigger_class VARCHAR(32),
    user_turn_text TEXT,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_tg_tickets_user_open
    ON training_ground_progression_tickets (user_id, status, priority, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tg_tickets_tier_open
    ON training_ground_progression_tickets (ticket_tier, status, created_at DESC)
    WHERE status = 'open';

-- CRISIS user_turn_text: assigned-coach only via REST; encrypt at rest v1.1 if needed.

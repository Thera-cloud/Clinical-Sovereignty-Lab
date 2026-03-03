-- Migration 068: Master/Assistant Coach Hierarchy + BLE Coaching Mesh
-- Tables: coach_hierarchy, supervised_hours, coaching_mesh_sessions/participants/messages
-- Trust baseline seed for coach_hierarchy_auditor (16 checks)

-- ── Coach Hierarchy ──

CREATE TABLE IF NOT EXISTS coach_hierarchy (
    id              SERIAL PRIMARY KEY,
    master_coach_id VARCHAR(64) NOT NULL,
    assistant_id    VARCHAR(64) NOT NULL,
    status          VARCHAR(20) DEFAULT 'pending',
    invited_at      TIMESTAMPTZ DEFAULT NOW(),
    accepted_at     TIMESTAMPTZ,
    revoked_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (master_coach_id, assistant_id)
);

CREATE INDEX IF NOT EXISTS idx_coach_hierarchy_master ON coach_hierarchy (master_coach_id);
CREATE INDEX IF NOT EXISTS idx_coach_hierarchy_assistant ON coach_hierarchy (assistant_id);
CREATE INDEX IF NOT EXISTS idx_coach_hierarchy_status ON coach_hierarchy (status);

-- ── Supervised Hours ──

CREATE TABLE IF NOT EXISTS supervised_hours (
    id                  SERIAL PRIMARY KEY,
    assistant_id        VARCHAR(64) NOT NULL,
    master_coach_id     VARCHAR(64) NOT NULL,
    activity_type       VARCHAR(64) DEFAULT 'individual_supervision',
    dojo_type           VARCHAR(32),
    duration_minutes    DOUBLE PRECISION NOT NULL,
    session_date        DATE DEFAULT CURRENT_DATE,
    notes               TEXT,
    attestation_status  VARCHAR(20) DEFAULT 'pending',
    attested_at         TIMESTAMPTZ,
    mesh_session_id     VARCHAR(64),
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_supervised_hours_assistant ON supervised_hours (assistant_id);
CREATE INDEX IF NOT EXISTS idx_supervised_hours_master ON supervised_hours (master_coach_id);
CREATE INDEX IF NOT EXISTS idx_supervised_hours_status ON supervised_hours (attestation_status);

-- ── Coaching Mesh Sessions ──

CREATE TABLE IF NOT EXISTS coaching_mesh_sessions (
    id                  SERIAL PRIMARY KEY,
    session_id          VARCHAR(64) UNIQUE NOT NULL,
    master_coach_id     VARCHAR(64) NOT NULL,
    session_type        VARCHAR(64),
    title               VARCHAR(256),
    topic_tags          JSONB DEFAULT '[]'::jsonb,
    dojo_context        VARCHAR(32),
    started_at          TIMESTAMPTZ DEFAULT NOW(),
    ended_at            TIMESTAMPTZ,
    participant_count   INTEGER DEFAULT 0,
    nate_participation  BOOLEAN DEFAULT true,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mesh_sessions_master ON coaching_mesh_sessions (master_coach_id);
CREATE INDEX IF NOT EXISTS idx_mesh_sessions_type ON coaching_mesh_sessions (session_type);
CREATE INDEX IF NOT EXISTS idx_mesh_sessions_dojo ON coaching_mesh_sessions (dojo_context);
CREATE INDEX IF NOT EXISTS idx_mesh_sessions_started ON coaching_mesh_sessions (started_at);

-- ── Coaching Mesh Participants ──

CREATE TABLE IF NOT EXISTS coaching_mesh_participants (
    id              SERIAL PRIMARY KEY,
    session_id      VARCHAR(64) NOT NULL REFERENCES coaching_mesh_sessions(session_id) ON DELETE CASCADE,
    user_id         VARCHAR(64) NOT NULL,
    role            VARCHAR(20),
    joined_at       TIMESTAMPTZ DEFAULT NOW(),
    left_at         TIMESTAMPTZ,
    ble_device_id   VARCHAR(128),
    UNIQUE (session_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_mesh_participants_session ON coaching_mesh_participants (session_id);
CREATE INDEX IF NOT EXISTS idx_mesh_participants_user ON coaching_mesh_participants (user_id);

-- ── Coaching Mesh Messages ──

CREATE TABLE IF NOT EXISTS coaching_mesh_messages (
    id                  SERIAL PRIMARY KEY,
    session_id          VARCHAR(64) NOT NULL REFERENCES coaching_mesh_sessions(session_id) ON DELETE CASCADE,
    sender_id           VARCHAR(64),
    message_type        VARCHAR(32),
    content             TEXT NOT NULL,
    metadata            JSONB,
    parent_message_id   INTEGER,
    score               DOUBLE PRECISION,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mesh_messages_session ON coaching_mesh_messages (session_id);
CREATE INDEX IF NOT EXISTS idx_mesh_messages_sender ON coaching_mesh_messages (sender_id);
CREATE INDEX IF NOT EXISTS idx_mesh_messages_type ON coaching_mesh_messages (message_type);
CREATE INDEX IF NOT EXISTS idx_mesh_messages_created ON coaching_mesh_messages (created_at);

-- ── Trust Baseline Seed ──

INSERT INTO trust_baseline (parameter_key, parameter_value, updated_at)
VALUES
    ('coach_hierarchy_check_count',
     '{"expected":16,"auditor":"CoachHierarchyAuditor","activity_type":"coach_hierarchy_audit_sent"}'::jsonb,
     NOW())
ON CONFLICT (parameter_key) DO UPDATE
SET parameter_value = EXCLUDED.parameter_value,
    updated_at = NOW();

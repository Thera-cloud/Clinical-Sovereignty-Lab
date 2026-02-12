-- =============================================================================
-- LITTLE NATE — PostgreSQL Database Schema
-- Version: 1.0
-- Date: January 21, 2026
-- Migrates from: user_registry.json (file-based)
-- =============================================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =============================================================================
-- CORE TABLES
-- =============================================================================

-- -----------------------------------------------------------------------------
-- FAMILIES: Family groupings with head of household
-- -----------------------------------------------------------------------------
CREATE TABLE families (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    family_code VARCHAR(20) UNIQUE NOT NULL,  -- e.g., FAM_0023
    name VARCHAR(100),                         -- e.g., "Thompson Family"
    head_of_household_id UUID,                 -- References users.id (set after user creation)
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------------------------
-- USERS: All platform users (clients, coaches, admins, researchers)
-- -----------------------------------------------------------------------------
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Credentials
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,       -- PBKDF2 hashed
    
    -- Profile
    role VARCHAR(20) NOT NULL CHECK (role IN ('CLIENT', 'COACH', 'ADMIN', 'RESEARCHER')),
    tier VARCHAR(20) DEFAULT 'STANDARD' CHECK (tier IN ('MASTER', 'SUPERVISOR', 'TOP', 'STANDARD', 'TRIAL', 'DEPENDENT')),
    name VARCHAR(100) NOT NULL,
    email VARCHAR(255),
    dob DATE,
    
    -- Family & Guardian
    family_id UUID REFERENCES families(id) ON DELETE SET NULL,
    guardian_id UUID REFERENCES users(id) ON DELETE SET NULL,
    is_minor BOOLEAN DEFAULT FALSE,
    
    -- Device & Security
    hardware_id VARCHAR(100),
    
    -- Consent
    consent_version VARCHAR(50),
    consent_date TIMESTAMP WITH TIME ZONE,
    consent_proxy VARCHAR(255),                -- "Signed by Guardian: username"
    
    -- Subscription
    subscription_status VARCHAR(30) DEFAULT 'TRIAL_ACTIVE' CHECK (
        subscription_status IN ('ACTIVE', 'TRIAL_ACTIVE', 'PENDING_VERIFICATION', 
                                'FAMILY_PLAN_ACTIVE', 'SUSPENDED', 'CANCELLED')
    ),
    
    -- Intake Data (JSONB for flexibility)
    intake_data JSONB DEFAULT '{"goals": [], "modality": "General"}',
    
    -- Coach-specific
    specialties TEXT[],                        -- Array of specialties
    coaching_style VARCHAR(50),                -- 'directive', 'reflective', 'integrative'
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP WITH TIME ZONE        -- Soft delete
);

-- Add foreign key for head of household after users table exists
ALTER TABLE families 
    ADD CONSTRAINT fk_families_hoh 
    FOREIGN KEY (head_of_household_id) REFERENCES users(id) ON DELETE SET NULL;

-- -----------------------------------------------------------------------------
-- SESSIONS: Therapy sessions (AI, Coach, Family)
-- -----------------------------------------------------------------------------
CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Participants
    user_id UUID NOT NULL REFERENCES users(id),
    coach_id UUID REFERENCES users(id),
    
    -- Session Details
    session_type VARCHAR(30) NOT NULL CHECK (session_type IN ('AI', 'COACH', 'FAMILY', 'GROUP')),
    platform VARCHAR(30) CHECK (platform IN ('IN_APP', 'ZOOM', 'FACETIME', 'PHONE')),
    
    -- Status & Timing
    status VARCHAR(20) DEFAULT 'SCHEDULED' CHECK (
        status IN ('SCHEDULED', 'CONFIRMED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED', 'NO_SHOW')
    ),
    scheduled_at TIMESTAMP WITH TIME ZONE,
    started_at TIMESTAMP WITH TIME ZONE,
    ended_at TIMESTAMP WITH TIME ZONE,
    duration_seconds INTEGER,
    
    -- Recording & Analysis
    recording_path VARCHAR(500),
    transcript_path VARCHAR(500),
    ai_analyzed BOOLEAN DEFAULT FALSE,
    
    -- Biometrics collected
    has_biometrics BOOLEAN DEFAULT FALSE,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------------------------
-- NEVEDAL_METRICS: Time-series quantum emotional coherence data
-- -----------------------------------------------------------------------------
CREATE TABLE nevedal_metrics (
    id BIGSERIAL PRIMARY KEY,
    
    -- References
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id),
    dyad_partner_id UUID REFERENCES users(id),  -- For coach-client dyad analysis
    
    -- Timestamp (high precision for real-time)
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    -- Core Nevedal Variables
    c_emo DECIMAL(6,5),           -- Quantum Emotional Coherence (0.00000-1.00000)
    p_ent DECIMAL(6,5),           -- Emotional Entanglement
    t_tunnel DECIMAL(6,5),        -- Tunneling Transparency
    gamma_env DECIMAL(6,5),       -- Decoherence Rate
    e_g_joint DECIMAL(6,5),       -- Joint Mass-Energy
    
    -- Derived Values
    tau_emo DECIMAL(10,5),        -- Coherence Lifetime
    d_distance DECIMAL(6,5),      -- Interpersonal Distance
    
    -- CEE Detection
    cee_window BOOLEAN DEFAULT FALSE,
    cee_duration_seconds INTEGER,
    
    -- Raw Biometrics (JSONB for flexibility)
    biometrics JSONB DEFAULT '{}'
    /*
    Example biometrics structure:
    {
        "subject_a": {
            "hrv_rmssd": 68,
            "resp_rate": 14,
            "gaze_contact": 0.78,
            "body_lean": 15,
            "eda": 2.3,
            "voice_stress": 0.23
        },
        "subject_b": {...},
        "synchrony": {
            "hrv": 0.89,
            "breath": 0.92,
            "gaze": 0.71,
            "posture": 0.88
        }
    }
    */
);

-- Index for time-series queries
CREATE INDEX idx_nevedal_metrics_user_time ON nevedal_metrics(user_id, recorded_at DESC);
CREATE INDEX idx_nevedal_metrics_session ON nevedal_metrics(session_id, recorded_at);

-- -----------------------------------------------------------------------------
-- MEMORY_LEDGER: Hippocampus - episodic memory per user
-- -----------------------------------------------------------------------------
CREATE TABLE memory_ledger (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id),
    session_id UUID REFERENCES sessions(id),
    
    -- Memory Content
    role VARCHAR(10) NOT NULL CHECK (role IN ('USER', 'NATE', 'COACH', 'SYSTEM')),
    content TEXT NOT NULL,
    
    -- Context
    coherence_at_time DECIMAL(5,4),
    modality VARCHAR(50),
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_memory_ledger_user ON memory_ledger(user_id, created_at DESC);

-- -----------------------------------------------------------------------------
-- WISDOM_ENTRIES: Night School - Little Nate's learned knowledge
-- -----------------------------------------------------------------------------
CREATE TABLE wisdom_entries (
    id SERIAL PRIMARY KEY,
    
    -- Versioning
    version VARCHAR(20) NOT NULL,              -- e.g., "v16.4"
    is_current BOOLEAN DEFAULT FALSE,
    
    -- Content
    category VARCHAR(50) NOT NULL,             -- 'crisis_intervention', 'cbt_techniques', etc.
    source VARCHAR(100),                       -- 'coach_notes', 'curriculum_pdf', 'manual_entry'
    source_file VARCHAR(255),                  -- Original filename
    content TEXT NOT NULL,
    
    -- Quality
    confidence DECIMAL(3,2) DEFAULT 0.50,
    
    -- Approval Workflow
    approved BOOLEAN DEFAULT FALSE,
    approved_by UUID REFERENCES users(id),
    approved_at TIMESTAMP WITH TIME ZONE,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_wisdom_current ON wisdom_entries(is_current, category);

-- -----------------------------------------------------------------------------
-- COACH_NOTES: Notes pending approval before ingestion
-- -----------------------------------------------------------------------------
CREATE TABLE coach_notes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Author & Context
    coach_id UUID NOT NULL REFERENCES users(id),
    session_id UUID REFERENCES sessions(id),
    client_id UUID NOT NULL REFERENCES users(id),
    
    -- Content
    content TEXT NOT NULL,
    
    -- PII Detection
    pii_detected BOOLEAN DEFAULT FALSE,
    pii_locations JSONB,                       -- [{start: 0, end: 10, type: "SSN"}]
    redacted_content TEXT,                     -- Version with PII removed
    
    -- Approval Workflow
    status VARCHAR(20) DEFAULT 'PENDING' CHECK (
        status IN ('PENDING', 'APPROVED', 'REJECTED', 'REDACTED')
    ),
    reviewed_by UUID REFERENCES users(id),
    reviewed_at TIMESTAMP WITH TIME ZONE,
    rejection_reason TEXT,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_coach_notes_status ON coach_notes(status, created_at);

-- -----------------------------------------------------------------------------
-- CRISIS_WATCHLIST: Deadman Switch monitoring
-- -----------------------------------------------------------------------------
CREATE TABLE crisis_watchlist (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- User being monitored
    user_id UUID NOT NULL REFERENCES users(id),
    
    -- Severity & Trigger
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('CRITICAL', 'WARNING', 'MONITORING')),
    trigger_type VARCHAR(50),                  -- 'keyword', 'silence', 'ai_flagged', 'manual'
    trigger_keyword VARCHAR(100),              -- e.g., "988", "suicide"
    trigger_context TEXT,
    
    -- Activity Tracking
    last_activity TIMESTAMP WITH TIME ZONE,
    silence_days INTEGER DEFAULT 0,
    silence_threshold_days INTEGER DEFAULT 3,
    
    -- Assignment
    assigned_coach_id UUID REFERENCES users(id),
    
    -- Notifications
    guardian_notified BOOLEAN DEFAULT FALSE,
    guardian_notified_at TIMESTAMP WITH TIME ZONE,
    coach_notified BOOLEAN DEFAULT FALSE,
    coach_notified_at TIMESTAMP WITH TIME ZONE,
    
    -- Resolution
    resolved BOOLEAN DEFAULT FALSE,
    resolved_at TIMESTAMP WITH TIME ZONE,
    resolved_by UUID REFERENCES users(id),
    resolution_notes TEXT,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_crisis_active ON crisis_watchlist(resolved, severity);

-- -----------------------------------------------------------------------------
-- AUDIT_LOG: Immutable administrative action log
-- -----------------------------------------------------------------------------
CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    
    -- Timestamp (not modifiable)
    logged_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    -- Actor
    admin_id UUID REFERENCES users(id),
    admin_username VARCHAR(50),
    admin_role VARCHAR(20),
    ip_address INET,
    user_agent TEXT,
    
    -- Action
    action_type VARCHAR(30) NOT NULL CHECK (
        action_type IN ('ACCESS', 'CREATE', 'MODIFY', 'DELETE', 'SECURITY', 
                        'LOGIN', 'LOGOUT', 'APPROVE', 'REJECT', 'EXPORT')
    ),
    
    -- Target
    target_type VARCHAR(30),                   -- 'user', 'session', 'wisdom', 'coach_note'
    target_id UUID,
    target_name VARCHAR(100),
    
    -- Details
    description TEXT NOT NULL,
    old_value JSONB,
    new_value JSONB,
    
    -- Compliance
    compliance_flags TEXT[]                    -- ['HIPAA', 'RTBF', 'GDPR']
);

-- Make audit log truly immutable
CREATE OR REPLACE FUNCTION prevent_audit_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Audit log is immutable. No updates or deletes allowed.';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_log_immutable
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION prevent_audit_modification();

-- Index for queries
CREATE INDEX idx_audit_log_time ON audit_log(logged_at DESC);
CREATE INDEX idx_audit_log_admin ON audit_log(admin_id, logged_at DESC);
CREATE INDEX idx_audit_log_target ON audit_log(target_type, target_id);

-- -----------------------------------------------------------------------------
-- COACH_AVAILABILITY: Scheduling slots
-- -----------------------------------------------------------------------------
CREATE TABLE coach_availability (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    coach_id UUID NOT NULL REFERENCES users(id),
    
    -- Slot Details
    day_of_week INTEGER CHECK (day_of_week BETWEEN 0 AND 6),  -- 0=Sunday
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    
    -- Or specific date
    specific_date DATE,
    
    -- Status
    is_available BOOLEAN DEFAULT TRUE,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_coach_availability ON coach_availability(coach_id, day_of_week);

-- -----------------------------------------------------------------------------
-- TOKENS: Active session tokens (replaces ACTIVE_TOKENS dict)
-- -----------------------------------------------------------------------------
CREATE TABLE active_tokens (
    token VARCHAR(64) PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    is_valid BOOLEAN DEFAULT TRUE
);

CREATE INDEX idx_tokens_user ON active_tokens(user_id);
CREATE INDEX idx_tokens_expiry ON active_tokens(expires_at);

-- -----------------------------------------------------------------------------
-- TOKEN_ECONOMICS: Azure API usage tracking
-- -----------------------------------------------------------------------------
CREATE TABLE token_economics (
    id BIGSERIAL PRIMARY KEY,
    
    -- Time bucket (hourly aggregation)
    hour_bucket TIMESTAMP WITH TIME ZONE NOT NULL,
    
    -- User (optional, for per-user tracking)
    user_id UUID REFERENCES users(id),
    tier VARCHAR(20),
    
    -- Token Counts
    tokens_text INTEGER DEFAULT 0,
    tokens_voice INTEGER DEFAULT 0,
    tokens_vision INTEGER DEFAULT 0,
    
    -- Costs (in cents)
    cost_text INTEGER DEFAULT 0,
    cost_voice INTEGER DEFAULT 0,
    cost_vision INTEGER DEFAULT 0,
    
    -- Unique constraint for upsert
    UNIQUE (hour_bucket, user_id)
);

CREATE INDEX idx_token_economics_time ON token_economics(hour_bucket DESC);

-- =============================================================================
-- FUNCTIONS & TRIGGERS
-- =============================================================================

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER families_updated_at BEFORE UPDATE ON families
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER sessions_updated_at BEFORE UPDATE ON sessions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- =============================================================================
-- MIGRATION HELPER: Import from user_registry.json
-- =============================================================================

-- This function can be called from Python to migrate existing users
-- Example: SELECT migrate_user_from_json('{"credentials": {...}, "profile": {...}}')

CREATE OR REPLACE FUNCTION migrate_user_from_json(user_json JSONB)
RETURNS UUID AS $$
DECLARE
    new_user_id UUID;
    creds JSONB;
    prof JSONB;
    fam_id UUID;
BEGIN
    creds := user_json->'credentials';
    prof := user_json->'profile';
    
    -- Handle family_id
    IF prof->>'family_id' IS NOT NULL AND prof->>'family_id' != 'null' THEN
        -- Create family if doesn't exist
        INSERT INTO families (family_code)
        VALUES (prof->>'family_id')
        ON CONFLICT (family_code) DO NOTHING;
        
        SELECT id INTO fam_id FROM families WHERE family_code = prof->>'family_id';
    END IF;
    
    -- Insert user
    INSERT INTO users (
        username,
        password_hash,
        role,
        tier,
        name,
        dob,
        family_id,
        hardware_id,
        consent_version,
        consent_date,
        consent_proxy,
        subscription_status,
        intake_data,
        is_minor
    ) VALUES (
        creds->>'username',
        creds->>'password',  -- Note: Should be hashed in production
        COALESCE(prof->>'role', 'CLIENT'),
        COALESCE(prof->>'tier', 'STANDARD'),
        COALESCE(prof->>'name', creds->>'username'),
        CASE WHEN prof->>'dob' IS NOT NULL THEN (prof->>'dob')::DATE ELSE NULL END,
        fam_id,
        prof->>'hardware_id',
        prof->>'consent_version',
        CASE WHEN prof->>'consent_date' IS NOT NULL THEN (prof->>'consent_date')::TIMESTAMP ELSE NULL END,
        prof->>'consent_proxy',
        COALESCE(prof->>'subscription_status', 'TRIAL_ACTIVE'),
        COALESCE(prof->'intake_data', '{"goals": [], "modality": "General"}'::JSONB),
        COALESCE((prof->>'is_minor')::BOOLEAN, FALSE)
    )
    RETURNING id INTO new_user_id;
    
    RETURN new_user_id;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- VIEWS FOR COMMON QUERIES
-- =============================================================================

-- Dashboard stats view
CREATE VIEW v_dashboard_stats AS
SELECT
    (SELECT COUNT(*) FROM users WHERE deleted_at IS NULL AND role = 'CLIENT') AS total_clients,
    (SELECT COUNT(*) FROM users WHERE deleted_at IS NULL AND role = 'COACH') AS total_coaches,
    (SELECT COUNT(*) FROM sessions WHERE status = 'IN_PROGRESS') AS live_sessions,
    (SELECT COUNT(*) FROM crisis_watchlist WHERE resolved = FALSE AND severity = 'CRITICAL') AS critical_alerts,
    (SELECT COUNT(*) FROM coach_notes WHERE status = 'PENDING') AS pending_notes,
    (SELECT COALESCE(SUM(cost_text + cost_voice + cost_vision), 0) 
     FROM token_economics 
     WHERE hour_bucket >= CURRENT_DATE) AS today_spend_cents;

-- Coach performance view
CREATE VIEW v_coach_performance AS
SELECT
    u.id AS coach_id,
    u.name AS coach_name,
    COUNT(DISTINCT s.id) AS total_sessions,
    COUNT(DISTINCT s.user_id) AS unique_clients,
    AVG(s.duration_seconds) AS avg_duration_seconds,
    COUNT(DISTINCT CASE WHEN s.status = 'COMPLETED' THEN s.id END) AS completed_sessions,
    COUNT(DISTINCT CASE WHEN nm.cee_window = TRUE THEN s.id END) AS sessions_with_cee
FROM users u
LEFT JOIN sessions s ON s.coach_id = u.id
LEFT JOIN nevedal_metrics nm ON nm.session_id = s.id
WHERE u.role = 'COACH' AND u.deleted_at IS NULL
GROUP BY u.id, u.name;

-- User Nevedal state view (latest metrics per user)
CREATE VIEW v_user_nevedal_state AS
SELECT DISTINCT ON (user_id)
    user_id,
    c_emo,
    p_ent,
    t_tunnel,
    gamma_env,
    e_g_joint,
    cee_window,
    recorded_at
FROM nevedal_metrics
ORDER BY user_id, recorded_at DESC;

-- =============================================================================
-- GRANTS (Adjust for your roles)
-- =============================================================================

-- Create application role
-- CREATE ROLE littlenate_app WITH LOGIN PASSWORD 'your_secure_password';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO littlenate_app;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO littlenate_app;

-- Read-only role for reporting
-- CREATE ROLE littlenate_readonly WITH LOGIN PASSWORD 'readonly_password';
-- GRANT SELECT ON ALL TABLES IN SCHEMA public TO littlenate_readonly;

-- =============================================================================
-- END OF SCHEMA
-- =============================================================================

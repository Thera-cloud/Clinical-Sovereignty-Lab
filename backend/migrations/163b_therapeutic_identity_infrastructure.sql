-- Migration 163: Therapeutic Identity Inference Engine — Infrastructure Tables
-- Creates tables for voice enrollment, linguistic identity, narrative identity,
-- institutional deployment, consent, and identity refinement.
-- Additive only: no ALTER or DROP on existing tables.

-- ============================================================================
-- Voice Enrollment Profiles
-- ============================================================================
CREATE TABLE IF NOT EXISTS voice_enrollment_profiles (
    id            UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id       TEXT NOT NULL,
    tenant_id     TEXT DEFAULT 'default',
    confidence_tier TEXT DEFAULT 'NONE' CHECK (confidence_tier IN ('NONE','LOW','MEDIUM','HIGH')),
    pitch_mean    FLOAT,
    pitch_variance FLOAT,
    energy_mean   FLOAT,
    speech_rate   FLOAT,
    spectral_centroid FLOAT,
    pause_ratio   FLOAT,
    session_count INT DEFAULT 0,
    greeting_features JSONB DEFAULT '{}',
    last_calibrated TIMESTAMPTZ,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, tenant_id)
);

-- ============================================================================
-- Linguistic Identity Fingerprints
-- ============================================================================
CREATE TABLE IF NOT EXISTS linguistic_fingerprints (
    id               UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id          TEXT NOT NULL,
    tenant_id        TEXT DEFAULT 'default',
    filler_distribution JSONB DEFAULT '{}',
    avg_sentence_length FLOAT,
    hedge_ratio      FLOAT,
    greeting_patterns JSONB DEFAULT '[]',
    vocabulary_richness FLOAT,
    utterance_count  INT DEFAULT 0,
    last_updated     TIMESTAMPTZ DEFAULT NOW(),
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, tenant_id)
);

-- ============================================================================
-- Narrative Identity Profiles
-- ============================================================================
CREATE TABLE IF NOT EXISTS narrative_identity_profiles (
    id               UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id          TEXT NOT NULL,
    tenant_id        TEXT DEFAULT 'default',
    themes           JSONB DEFAULT '{}',
    attachment_style TEXT,
    known_stories    JSONB DEFAULT '[]',
    relationship_patterns JSONB DEFAULT '[]',
    emotional_vocabulary JSONB DEFAULT '{}',
    turn_count       INT DEFAULT 0,
    last_updated     TIMESTAMPTZ DEFAULT NOW(),
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, tenant_id)
);

-- ============================================================================
-- Institutional Tenants
-- ============================================================================
CREATE TABLE IF NOT EXISTS institutional_tenants (
    id                  UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id           TEXT NOT NULL UNIQUE,
    name                TEXT NOT NULL,
    deployment_context  TEXT NOT NULL DEFAULT 'default',
    twilio_number       TEXT,
    admin_email         TEXT,
    config              JSONB DEFAULT '{}',
    consent_version     TEXT DEFAULT 'v1.0',
    active              BOOLEAN DEFAULT true,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Insert the default tenant
INSERT INTO institutional_tenants (tenant_id, name, deployment_context)
VALUES ('default', 'Sovereign Sanctuary', 'default')
ON CONFLICT (tenant_id) DO NOTHING;

-- ============================================================================
-- Consent Records
-- ============================================================================
CREATE TABLE IF NOT EXISTS consent_records (
    id               UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id          TEXT NOT NULL,
    tenant_id        TEXT NOT NULL DEFAULT 'default',
    consent_type     TEXT NOT NULL,
    granted          BOOLEAN DEFAULT false,
    consent_method   TEXT DEFAULT 'sms_magic_link',
    consent_source   TEXT,
    parent_user_id   TEXT,
    granted_at       TIMESTAMPTZ,
    expires_at       TIMESTAMPTZ,
    revoked_at       TIMESTAMPTZ,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, tenant_id, consent_type)
);

-- ============================================================================
-- Consent Requests (Magic Link tracking)
-- ============================================================================
CREATE TABLE IF NOT EXISTS consent_requests (
    id               UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    request_id       TEXT NOT NULL UNIQUE,
    user_id          TEXT NOT NULL,
    tenant_id        TEXT NOT NULL DEFAULT 'default',
    consent_type     TEXT NOT NULL,
    magic_link_hash  TEXT NOT NULL,
    phone            TEXT,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    expires_at       TIMESTAMPTZ,
    fulfilled        BOOLEAN DEFAULT false
);

-- ============================================================================
-- Data Deletion Queue (consent revocation cleanup)
-- ============================================================================
CREATE TABLE IF NOT EXISTS data_deletion_queue (
    id               UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id          TEXT NOT NULL,
    tenant_id        TEXT NOT NULL DEFAULT 'default',
    data_type        TEXT NOT NULL,
    scheduled_at     TIMESTAMPTZ DEFAULT NOW(),
    execute_after    TIMESTAMPTZ NOT NULL,
    executed_at      TIMESTAMPTZ,
    status           TEXT DEFAULT 'pending' CHECK (status IN ('pending','executing','completed','failed'))
);

-- ============================================================================
-- Identity Refinement Log
-- ============================================================================
CREATE TABLE IF NOT EXISTS identity_refinement_log (
    id                 UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id            TEXT NOT NULL,
    call_sid           TEXT,
    voice_updated      BOOLEAN DEFAULT false,
    linguistic_updated BOOLEAN DEFAULT false,
    narrative_updated  BOOLEAN DEFAULT false,
    excluded_reason    TEXT,
    drift_detected     BOOLEAN DEFAULT false,
    drift_magnitude    FLOAT DEFAULT 0.0,
    consecutive_drifts INT DEFAULT 0,
    refined_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_identity_refinement_user
    ON identity_refinement_log (user_id, refined_at DESC);

-- ============================================================================
-- Identity Drift Flags (manual review queue)
-- ============================================================================
CREATE TABLE IF NOT EXISTS identity_drift_flags (
    id               UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id          TEXT NOT NULL,
    call_sid         TEXT,
    drift_magnitude  FLOAT NOT NULL,
    flagged_at       TIMESTAMPTZ DEFAULT NOW(),
    reviewed         BOOLEAN DEFAULT false,
    reviewed_by      TEXT,
    reviewed_at      TIMESTAMPTZ,
    review_notes     TEXT
);

CREATE INDEX IF NOT EXISTS idx_identity_drift_unreviewed
    ON identity_drift_flags (reviewed, flagged_at DESC)
    WHERE NOT reviewed;

-- ============================================================================
-- Identity Inference History (per-call identity decision log)
-- ============================================================================
CREATE TABLE IF NOT EXISTS identity_inference_log (
    id               UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    call_sid         TEXT NOT NULL,
    phone            TEXT,
    tenant_id        TEXT DEFAULT 'default',
    top_candidate    TEXT,
    confidence       FLOAT,
    method           TEXT,
    voice_score      FLOAT,
    linguistic_score FLOAT,
    narrative_score  FLOAT,
    osd_penalty      FLOAT DEFAULT 0.0,
    liveness_ok      BOOLEAN DEFAULT true,
    roleplay_excluded BOOLEAN DEFAULT false,
    qos_degraded     BOOLEAN DEFAULT false,
    gentle_investigation BOOLEAN DEFAULT false,
    environment      TEXT DEFAULT 'individual',
    inferred_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_identity_inference_call
    ON identity_inference_log (call_sid);
CREATE INDEX IF NOT EXISTS idx_identity_inference_candidate
    ON identity_inference_log (top_candidate, inferred_at DESC);

-- ============================================================================
-- Voice Mandatory Reporting Events
-- ============================================================================
CREATE TABLE IF NOT EXISTS voice_mandatory_reporting_events (
    id               UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    call_sid         TEXT NOT NULL,
    user_id          TEXT NOT NULL,
    category         TEXT NOT NULL,
    detection_source TEXT DEFAULT 'voice_ai',
    detected_at      TIMESTAMPTZ DEFAULT NOW(),
    escalated        BOOLEAN DEFAULT false,
    reviewed         BOOLEAN DEFAULT false,
    reviewed_by      TEXT,
    reviewed_at      TIMESTAMPTZ,
    UNIQUE (call_sid, category)
);

CREATE INDEX IF NOT EXISTS idx_voice_reporting_unreviewed
    ON voice_mandatory_reporting_events (reviewed, detected_at DESC)
    WHERE NOT reviewed;

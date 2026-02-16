-- Migration 028: Me-2-Me Platinum Tables
-- Consent, Identity Crystal, Avatar, Growth, Family Fabric, Migration, Trust

-- =============================================================================
-- CONSENT
-- =============================================================================

CREATE TABLE IF NOT EXISTS me2me_consent_records (
    consent_id      TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    level           TEXT NOT NULL,
    status          TEXT DEFAULT 'pending',
    granted_at      TIMESTAMPTZ,
    revoked_at      TIMESTAMPTZ,
    renewal_due     TIMESTAMPTZ,
    witness_signature TEXT,
    legal_notice_acknowledged BOOLEAN DEFAULT FALSE,
    version         INTEGER DEFAULT 1,
    audit_trail     JSONB DEFAULT '[]'::jsonb,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT fk_consent_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_consent_user ON me2me_consent_records(user_id);
CREATE INDEX IF NOT EXISTS idx_consent_status ON me2me_consent_records(status);

-- =============================================================================
-- IMPRINT ACCUMULATOR
-- =============================================================================

CREATE TABLE IF NOT EXISTS me2me_imprint_entries (
    entry_id        TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    source          TEXT DEFAULT '',
    content         TEXT DEFAULT '',
    content_hash    TEXT DEFAULT '',
    themes          JSONB DEFAULT '[]'::jsonb,
    emotions        JSONB DEFAULT '[]'::jsonb,
    voice_biometrics JSONB,
    c_emo_at_capture FLOAT DEFAULT 0,
    gamma_at_capture FLOAT DEFAULT 0,
    captured_at     TIMESTAMPTZ DEFAULT NOW(),
    processed       BOOLEAN DEFAULT FALSE,
    CONSTRAINT fk_imprint_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_imprint_user ON me2me_imprint_entries(user_id);
CREATE INDEX IF NOT EXISTS idx_imprint_processed ON me2me_imprint_entries(processed);

-- =============================================================================
-- IDENTITY CRYSTAL
-- =============================================================================

CREATE TABLE IF NOT EXISTS me2me_identity_crystals (
    crystal_id      TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    crystal_version INTEGER DEFAULT 1,
    personality     JSONB DEFAULT '{}'::jsonb,
    language_sig    JSONB DEFAULT '{}'::jsonb,
    humor           JSONB DEFAULT '{}'::jsonb,
    core_values     JSONB DEFAULT '[]'::jsonb,
    life_themes     JSONB DEFAULT '[]'::jsonb,
    relationship_patterns JSONB DEFAULT '{}'::jsonb,
    therapeutic_journey_summary TEXT DEFAULT '',
    growth_narrative TEXT DEFAULT '',
    wisdom_distilled JSONB DEFAULT '[]'::jsonb,
    coherence_signature JSONB DEFAULT '{}'::jsonb,
    confidence_score FLOAT DEFAULT 0,
    data_points_used INTEGER DEFAULT 0,
    sessions_analyzed INTEGER DEFAULT 0,
    synthesized_at  TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT fk_crystal_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_crystal_user ON me2me_identity_crystals(user_id);

-- =============================================================================
-- AVATAR CORE
-- =============================================================================

CREATE TABLE IF NOT EXISTS me2me_avatars (
    avatar_id       TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    display_name    TEXT DEFAULT '',
    status          TEXT DEFAULT 'inactive',
    crystal_version_locked INTEGER DEFAULT 0,
    latest_crystal_id TEXT REFERENCES me2me_identity_crystals(crystal_id),
    activation_date TIMESTAMPTZ,
    total_visitor_sessions INTEGER DEFAULT 0,
    total_interactions INTEGER DEFAULT 0,
    grief_monitoring_active BOOLEAN DEFAULT TRUE,
    response_accuracy_score FLOAT DEFAULT 0,
    family_fabric_id TEXT,
    ethical_boundaries JSONB DEFAULT '{}'::jsonb,
    growth_layers   JSONB DEFAULT '[]'::jsonb,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT fk_avatar_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_avatar_user ON me2me_avatars(user_id);
CREATE INDEX IF NOT EXISTS idx_avatar_status ON me2me_avatars(status);

-- =============================================================================
-- GROWTH ENGINE
-- =============================================================================

CREATE TABLE IF NOT EXISTS me2me_growth_layers (
    layer_id        TEXT PRIMARY KEY,
    avatar_id       TEXT NOT NULL REFERENCES me2me_avatars(avatar_id) ON DELETE CASCADE,
    knowledge_source TEXT DEFAULT '',
    knowledge_type  TEXT DEFAULT 'general',
    content_summary TEXT DEFAULT '',
    clearly_marked_as_post BOOLEAN DEFAULT TRUE,
    confidence      FLOAT DEFAULT 0,
    acquired_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_growth_avatar ON me2me_growth_layers(avatar_id);

-- =============================================================================
-- FAMILY FABRIC
-- =============================================================================

CREATE TABLE IF NOT EXISTS me2me_family_fabrics (
    fabric_id       TEXT PRIMARY KEY,
    family_id       TEXT NOT NULL,
    member_avatars  JSONB DEFAULT '{}'::jsonb,
    relationship_map JSONB DEFAULT '{}'::jsonb,
    shared_memories JSONB DEFAULT '[]'::jsonb,
    family_themes   JSONB DEFAULT '[]'::jsonb,
    transgenerational_patterns JSONB DEFAULT '[]'::jsonb,
    cross_avatar_interactions INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fabric_family ON me2me_family_fabrics(family_id);

-- =============================================================================
-- MIGRATION (Organic-to-Inorganic Transition)
-- =============================================================================

CREATE TABLE IF NOT EXISTS me2me_migrations (
    migration_id    TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    phase           TEXT DEFAULT 'not_started',
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    trigger         TEXT DEFAULT 'manual',
    data_completeness_score FLOAT DEFAULT 0,
    crystal_quality_score FLOAT DEFAULT 0,
    avatar_readiness_score FLOAT DEFAULT 0,
    guardian_id     TEXT,
    guardian_notified BOOLEAN DEFAULT FALSE,
    legal_trust_linked BOOLEAN DEFAULT FALSE,
    final_words_recorded BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT fk_migration_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- =============================================================================
-- TRUST & LEGAL
-- =============================================================================

CREATE TABLE IF NOT EXISTS me2me_sovereign_trusts (
    trust_id        TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    trust_name      TEXT DEFAULT '',
    grantor_name    TEXT DEFAULT '',
    trustee_contact TEXT,
    funding_method  TEXT DEFAULT 'subscription',
    annual_funding_amount FLOAT DEFAULT 0,
    tax_id          TEXT,
    jurisdiction    TEXT DEFAULT 'US',
    established_date TIMESTAMPTZ,
    perpetuity_duration_years INTEGER DEFAULT 100,
    successor_guardian_chain JSONB DEFAULT '[]'::jsonb,
    status          TEXT DEFAULT 'draft',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT fk_trust_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS me2me_trust_beneficiaries (
    beneficiary_id  TEXT PRIMARY KEY,
    trust_id        TEXT NOT NULL REFERENCES me2me_sovereign_trusts(trust_id) ON DELETE CASCADE,
    name            TEXT DEFAULT '',
    relationship    TEXT DEFAULT '',
    email           TEXT,
    access_level    TEXT DEFAULT 'visitor',
    age_gate        INTEGER,
    age_gate_content_filters JSONB DEFAULT '[]'::jsonb,
    guardian_id     TEXT
);

CREATE INDEX IF NOT EXISTS idx_beneficiary_trust ON me2me_trust_beneficiaries(trust_id);

CREATE TABLE IF NOT EXISTS me2me_trust_funding (
    funding_id      TEXT PRIMARY KEY,
    trust_id        TEXT NOT NULL REFERENCES me2me_sovereign_trusts(trust_id) ON DELETE CASCADE,
    funding_type    TEXT DEFAULT 'subscription',
    amount          FLOAT DEFAULT 0,
    currency        TEXT DEFAULT 'USD',
    stripe_subscription_id TEXT,
    stripe_payment_intent_id TEXT,
    funded_at       TIMESTAMPTZ DEFAULT NOW(),
    next_funding_due TIMESTAMPTZ,
    status          TEXT DEFAULT 'active'
);

-- =============================================================================
-- VISITOR SESSIONS (for post-activation interaction)
-- =============================================================================

CREATE TABLE IF NOT EXISTS me2me_visitor_sessions (
    session_id      TEXT PRIMARY KEY,
    avatar_id       TEXT NOT NULL REFERENCES me2me_avatars(avatar_id) ON DELETE CASCADE,
    visitor_id      TEXT NOT NULL,
    visitor_relationship TEXT DEFAULT '',
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    ended_at        TIMESTAMPTZ,
    messages        JSONB DEFAULT '[]'::jsonb,
    grief_indicators JSONB DEFAULT '[]'::jsonb,
    grief_level     FLOAT DEFAULT 0,
    grief_cooldown_triggered BOOLEAN DEFAULT FALSE,
    duration_seconds INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_visitor_avatar ON me2me_visitor_sessions(avatar_id);
CREATE INDEX IF NOT EXISTS idx_visitor_id ON me2me_visitor_sessions(visitor_id);

-- =============================================================================
-- DATA PORTABILITY (SLF)
-- =============================================================================

CREATE TABLE IF NOT EXISTS slf_export_requests (
    request_id      TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    requested_by    TEXT DEFAULT '',
    sections        JSONB DEFAULT '[]'::jsonb,
    include_me2me   BOOLEAN DEFAULT TRUE,
    encryption_algorithm TEXT DEFAULT 'AES-256-GCM',
    approved        BOOLEAN DEFAULT FALSE,
    approved_at     TIMESTAMPTZ,
    status          TEXT DEFAULT 'pending',
    file_path       TEXT,
    file_size_bytes BIGINT DEFAULT 0,
    requested_at    TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS slf_import_requests (
    request_id      TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    archive_path    TEXT DEFAULT '',
    archive_size_bytes BIGINT DEFAULT 0,
    manifest_validated BOOLEAN DEFAULT FALSE,
    checksum_verified BOOLEAN DEFAULT FALSE,
    conflict_resolution TEXT DEFAULT 'skip_existing',
    status          TEXT DEFAULT 'pending',
    errors          JSONB DEFAULT '[]'::jsonb,
    requested_at    TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

-- Migration 223: Family System Field (FSF) — unified family dynamics brief
-- Additive only. No Sensitive Bridge table FKs; username-scoped subject rows.

CREATE TABLE IF NOT EXISTS family_system_field_entries (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_id       TEXT NOT NULL,
    subject_username VARCHAR(255),
    visibility_lane  VARCHAR(32) NOT NULL,
    sensitivity_class VARCHAR(32) NOT NULL DEFAULT 'public',
    source_surface   VARCHAR(64) NOT NULL,
    source_ref       VARCHAR(255),
    content          TEXT NOT NULL,
    content_hash     CHAR(64) NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    superseded_at    TIMESTAMPTZ,
    CONSTRAINT fsf_lane_check CHECK (
        visibility_lane IN (
            'system_dynamics', 'sanctuary_shared', 'member_abstract', 'coach_clinical', 'quarantine'
        )
    ),
    CONSTRAINT fsf_sensitivity_check CHECK (
        sensitivity_class IN ('public', 'coach_only', 'quarantined')
    ),
    CONSTRAINT fsf_content_len CHECK (char_length(content) <= 2000)
);

CREATE INDEX IF NOT EXISTS idx_fsf_family_active
    ON family_system_field_entries (family_id, visibility_lane)
    WHERE superseded_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_fsf_subject_active
    ON family_system_field_entries (family_id, subject_username)
    WHERE superseded_at IS NULL AND subject_username IS NOT NULL;

CREATE TABLE IF NOT EXISTS family_system_field_audit (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_id          TEXT,
    requester_username VARCHAR(255),
    event_type         VARCHAR(64) NOT NULL,
    payload_json       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fsf_audit_family_time
    ON family_system_field_audit (family_id, created_at DESC);

COMMENT ON TABLE family_system_field_entries IS
    'Family System Field (FSF): de-identified system brief lanes keyed by family_id. '
    'Never stores Sensitive Bridge rows or raw private transcripts.';

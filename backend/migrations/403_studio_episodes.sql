-- Sovereign Studio S1 — episodes, flags, learning, overrides, meter.
-- Additive only. QUANTUM-CRYSTAL-ARCH
-- INV-3: approve is application-gated; no auto-publish trigger.

CREATE TABLE IF NOT EXISTS studio_episodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    show_id UUID NOT NULL REFERENCES studio_shows (id),
    session_id UUID REFERENCES studio_sessions (id),
    state TEXT NOT NULL DEFAULT 'in_review',
    title TEXT,
    transcript_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    cuts_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    approved_by VARCHAR,
    approved_at TIMESTAMPTZ,
    published_at TIMESTAMPTZ,
    rss_guid TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT studio_episodes_state_chk CHECK (
        state IN ('in_review', 'approved', 'published', 'rejected')
    )
);

CREATE INDEX IF NOT EXISTS idx_studio_episodes_show
    ON studio_episodes (show_id, created_at DESC);

CREATE TABLE IF NOT EXISTS studio_compliance_flags (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    episode_id UUID NOT NULL REFERENCES studio_episodes (id),
    severity TEXT NOT NULL,
    category TEXT NOT NULL,
    detail TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT studio_flag_severity_chk CHECK (severity IN ('low', 'med', 'high')),
    CONSTRAINT studio_flag_status_chk CHECK (status IN ('open', 'resolved', 'overridden'))
);

CREATE INDEX IF NOT EXISTS idx_studio_flags_episode
    ON studio_compliance_flags (episode_id, status);

CREATE TABLE IF NOT EXISTS studio_compliance_flag_overrides (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    flag_id UUID NOT NULL REFERENCES studio_compliance_flags (id),
    episode_id UUID NOT NULL REFERENCES studio_episodes (id),
    severity TEXT NOT NULL,
    reason TEXT NOT NULL,
    overridden_by VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS studio_show_learning (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    show_id UUID NOT NULL REFERENCES studio_shows (id),
    kind TEXT NOT NULL,
    payload_deidentified JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS studio_meter (
    show_id UUID NOT NULL REFERENCES studio_shows (id),
    day DATE NOT NULL,
    session_minutes NUMERIC NOT NULL DEFAULT 0,
    caller_minutes NUMERIC NOT NULL DEFAULT 0,
    egress_bytes BIGINT NOT NULL DEFAULT 0,
    youtube_pushes INT NOT NULL DEFAULT 0,
    PRIMARY KEY (show_id, day)
);

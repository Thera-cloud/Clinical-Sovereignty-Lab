-- Sovereign Studio S1 schema for S2 caller pipeline. Tables only — no screener runtime yet.
-- Additive only. QUANTUM-CRYSTAL-ARCH

CREATE TABLE IF NOT EXISTS show_callers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    show_id UUID NOT NULL REFERENCES studio_shows (id),
    session_id UUID REFERENCES studio_sessions (id),
    phone_hash TEXT,
    display_name TEXT,
    opted_in BOOLEAN NOT NULL DEFAULT FALSE,
    risk_flag BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_show_callers_show
    ON show_callers (show_id, created_at DESC);

CREATE TABLE IF NOT EXISTS caller_topics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    caller_id UUID NOT NULL REFERENCES show_callers (id),
    topic_deidentified TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Do not create public.consent_records — that table is identity/workspace (163b/328).
-- Studio consents live in studio_consent_records (migration 408).

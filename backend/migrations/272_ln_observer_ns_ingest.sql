-- Migration 272: LN-Observer Night School ingest queue + trust baseline
-- Additive only. Phase 2 bulk transcript → NS path.

CREATE TABLE IF NOT EXISTS ln_observer_ns_ingest (
    id              BIGSERIAL PRIMARY KEY,
    session_id      UUID NOT NULL
                    REFERENCES ln_observer_sessions(session_id) ON DELETE CASCADE,
    coach_id        TEXT NOT NULL,
    chunk_text      TEXT NOT NULL,
    pii_cleared     BOOLEAN NOT NULL DEFAULT FALSE,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'ingested', 'failed', 'skipped')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    ingested_at     TIMESTAMPTZ,
    error           TEXT
);

CREATE INDEX IF NOT EXISTS idx_lnobs_ns_ingest_pending
    ON ln_observer_ns_ingest (status, created_at)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_lnobs_ns_ingest_session
    ON ln_observer_ns_ingest (session_id);

INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES (
    'ln_observer_check_count',
    '{"expected": 11, "description": "LN-Observer trust checks (7 REST + 4 DB)", "updated": "2026-07-23"}'::jsonb
)
ON CONFLICT (parameter_key) DO UPDATE
SET parameter_value = EXCLUDED.parameter_value,
    updated_at = NOW();

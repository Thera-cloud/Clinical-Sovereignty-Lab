-- Coach override audit trail + TTL columns for pacing / focus_domain

CREATE TABLE IF NOT EXISTS coach_override_audit (
    id              SERIAL PRIMARY KEY,
    coach_user_id   VARCHAR NOT NULL,
    client_user_id  VARCHAR NOT NULL,
    override_type   VARCHAR NOT NULL,
    previous_value  TEXT,
    new_value       TEXT,
    reason          TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_override_audit_client
    ON coach_override_audit (client_user_id);

CREATE INDEX IF NOT EXISTS idx_override_audit_coach_client
    ON coach_override_audit (coach_user_id, client_user_id, created_at DESC);

ALTER TABLE coach_client_overrides
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;

ALTER TABLE coach_client_overrides
    ADD COLUMN IF NOT EXISTS focus_domain_expires_at TIMESTAMPTZ;

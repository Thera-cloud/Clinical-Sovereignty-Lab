-- Studio HMAC secrets (encrypted) + engagement idempotency.
CREATE TABLE IF NOT EXISTS studio_webhook_secrets (
    coach_id VARCHAR PRIMARY KEY,
    secret_ciphertext TEXT NOT NULL,
    fingerprint TEXT,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS studio_hook_events (
    coach_id VARCHAR NOT NULL,
    event_id TEXT NOT NULL,
    hook TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (coach_id, event_id)
);

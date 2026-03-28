-- Migration 118: Nate Summon System
-- Universal summon infrastructure: tokens, public bottle tracking, interaction log

CREATE TABLE IF NOT EXISTS summon_tokens (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(100) NOT NULL REFERENCES users(username),
    token         VARCHAR(128) NOT NULL UNIQUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at    TIMESTAMPTZ,
    last_used_at  TIMESTAMPTZ,
    channel       VARCHAR(50),
    is_active     BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS public_summon_usage (
    id                  SERIAL PRIMARY KEY,
    device_fingerprint  VARCHAR(128) NOT NULL,
    ip_address          INET,
    queries_used        INT DEFAULT 0,
    first_query_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_query_at       TIMESTAMPTZ,
    converted           BOOLEAN DEFAULT FALSE,
    converted_username  VARCHAR(100)
);

CREATE TABLE IF NOT EXISTS summon_interactions (
    id              SERIAL PRIMARY KEY,
    username        VARCHAR(100),
    device_fingerprint VARCHAR(128),
    channel         VARCHAR(50) NOT NULL,
    user_message    TEXT NOT NULL,
    nate_response   TEXT,
    access_level    VARCHAR(20) NOT NULL,
    tokens_used     INT DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_public_summon_fp
    ON public_summon_usage(device_fingerprint);

CREATE INDEX IF NOT EXISTS idx_summon_tokens_token
    ON summon_tokens(token);

CREATE INDEX IF NOT EXISTS idx_summon_tokens_username
    ON summon_tokens(username);

CREATE INDEX IF NOT EXISTS idx_summon_interactions_username
    ON summon_interactions(username);

CREATE INDEX IF NOT EXISTS idx_summon_interactions_created
    ON summon_interactions(created_at);

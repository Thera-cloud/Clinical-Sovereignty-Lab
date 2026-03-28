-- Migration 145: Nevedal Coding Domain State + Coherence Log
-- Tracks dual-brain C_emo evolution for the coding intelligence pipeline.

CREATE TABLE IF NOT EXISTS nevedal_domain_state (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain       TEXT NOT NULL UNIQUE,
    p_ent        FLOAT NOT NULL DEFAULT 0.0,
    T_tunnel     FLOAT NOT NULL DEFAULT 0.37,
    gamma_env    FLOAT NOT NULL DEFAULT 0.80,
    E_G          FLOAT NOT NULL DEFAULT 0.45,
    beta         FLOAT NOT NULL DEFAULT 1.0,
    C_emo        FLOAT NOT NULL DEFAULT 0.0,
    crystal_count INT NOT NULL DEFAULT 0,
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS nevedal_coherence_log (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain       TEXT NOT NULL,
    C_emo        FLOAT NOT NULL,
    p_ent        FLOAT NOT NULL,
    T_tunnel     FLOAT NOT NULL,
    gamma_env    FLOAT NOT NULL,
    E_G          FLOAT,
    similarity   FLOAT,
    signal       TEXT,
    provider     TEXT,
    crystal_count INT,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_coherence_log_domain_time
    ON nevedal_coherence_log(domain, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_coherence_log_cemo
    ON nevedal_coherence_log(C_emo DESC);

-- Seed initial coding domain state
INSERT INTO nevedal_domain_state (domain, gamma_env)
    VALUES ('coding', 0.80)
    ON CONFLICT (domain) DO NOTHING;

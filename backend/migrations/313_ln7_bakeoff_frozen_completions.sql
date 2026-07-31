-- Attempt 5: decoupled bakeoff — freeze completions (Phase A) then score offline (Phase B).
-- QUANTUM-CRYSTAL-ARCH
-- Additive only.

CREATE TABLE IF NOT EXISTS ln7_bakeoff_frozen_completions (
    id                BIGSERIAL PRIMARY KEY,
    burst_id          TEXT NOT NULL,
    prompt_hash       TEXT NOT NULL,
    pack_id           TEXT NOT NULL,
    task_id           TEXT NOT NULL DEFAULT '',
    arm_revision_id   TEXT NOT NULL,
    adapter_sha       TEXT NOT NULL DEFAULT '',
    raw_text          TEXT,
    gen_error         TEXT,
    gen_latency_ms    INTEGER,
    is_anchor         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ln7_frozen_raw_or_error CHECK (
        (raw_text IS NOT NULL AND LENGTH(TRIM(raw_text)) > 0)
        OR (gen_error IS NOT NULL AND LENGTH(TRIM(gen_error)) > 0)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ln7_frozen_burst_arm_pack_task
    ON ln7_bakeoff_frozen_completions (burst_id, arm_revision_id, pack_id, task_id);

CREATE INDEX IF NOT EXISTS idx_ln7_frozen_burst
    ON ln7_bakeoff_frozen_completions (burst_id);

CREATE TABLE IF NOT EXISTS ln7_bakeoff_verdicts (
    id                BIGSERIAL PRIMARY KEY,
    burst_id          TEXT NOT NULL UNIQUE,
    rev_a             TEXT NOT NULL,
    rev_b             TEXT NOT NULL,
    winner            TEXT,
    mean_a            DOUBLE PRECISION,
    mean_b            DOUBLE PRECISION,
    lo_a              DOUBLE PRECISION,
    hi_a              DOUBLE PRECISION,
    lo_b              DOUBLE PRECISION,
    hi_b              DOUBLE PRECISION,
    n_a               INTEGER NOT NULL DEFAULT 0,
    n_b               INTEGER NOT NULL DEFAULT 0,
    anchor_score      DOUBLE PRECISION,
    smoke_ok          BOOLEAN NOT NULL DEFAULT FALSE,
    payload_json      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

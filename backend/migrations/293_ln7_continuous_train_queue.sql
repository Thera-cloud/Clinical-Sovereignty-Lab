-- LN7 continuous gated self-improvement control plane (coder-domain only).
-- Queue micro-batches from graded outcomes / preference events → worker → shadow canary → policy promote.
-- QUANTUM-CRYSTAL-ARCH

CREATE TABLE IF NOT EXISTS ln7_train_jobs (
    id              BIGSERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status          TEXT NOT NULL DEFAULT 'queued'
                    CHECK (status IN (
                        'queued', 'exporting', 'training', 'registering',
                        'canary', 'promoted', 'rolled_back', 'failed', 'skipped'
                    )),
    trigger_source  TEXT NOT NULL DEFAULT 'outcome'
                    CHECK (trigger_source IN ('outcome', 'usage_reject', 'usage_edit', 'schedule', 'manual')),
    outcome_ids     BIGINT[] NOT NULL DEFAULT '{}',
    batch_n         INT NOT NULL DEFAULT 0,
    train_jsonl_path TEXT,
    adapter_path    TEXT,
    revision_id     TEXT,
    gate_json       JSONB NOT NULL DEFAULT '{}'::jsonb,
    error           TEXT,
    worker_host     TEXT,
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_ln7_train_jobs_status_created
    ON ln7_train_jobs (status, created_at);

CREATE TABLE IF NOT EXISTS ln7_canary_state (
    id              BIGSERIAL PRIMARY KEY,
    revision_id     TEXT NOT NULL UNIQUE,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    traffic_pct     REAL NOT NULL DEFAULT 5.0,
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'promoted', 'rolled_back', 'expired')),
    pass_rate_json  JSONB NOT NULL DEFAULT '{}'::jsonb,
    incumbent_id    TEXT,
    last_check_at   TIMESTAMPTZ,
    notes           TEXT
);

-- Policy knobs (defaults; overridable by env)
INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES (
    'ln7_continuous_train_batch_n',
    '{"expected": 8, "min_batch": 4, "canary_pct": 5}'::jsonb
)
ON CONFLICT (parameter_key) DO NOTHING;

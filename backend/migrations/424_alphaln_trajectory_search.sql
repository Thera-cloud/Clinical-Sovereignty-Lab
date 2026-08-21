-- Migration 424: AlphaLN Slice 6 — Trajectory search prototype (Loop C skeleton)
--
-- Records planned + expanded trajectory-search runs (MCTS-style rollout over
-- reactive patient sims). Skeleton only — the search engine itself is a stub
-- that returns "not_implemented" until ENABLE_ALPHALN_TRAJECTORY_SEARCH flips.
--
-- Feature flag: ENABLE_ALPHALN_TRAJECTORY_SEARCH (default false).

CREATE TABLE IF NOT EXISTS alphaln_trajectory_runs (
    id                 BIGSERIAL PRIMARY KEY,
    admin_user         TEXT NOT NULL,
    started_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at        TIMESTAMPTZ,
    status             TEXT NOT NULL DEFAULT 'queued'
                       CHECK (status IN ('queued','running','complete','error','flag_off')),
    root_seed          TEXT NOT NULL,          -- opaque seed / scenario id
    max_depth          INTEGER NOT NULL DEFAULT 3,
    max_rollouts       INTEGER NOT NULL DEFAULT 8,
    best_score         NUMERIC(6,3),
    error_text         TEXT,
    result_summary     JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata           JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_alphaln_traj_runs_started
    ON alphaln_trajectory_runs(started_at DESC);

CREATE TABLE IF NOT EXISTS alphaln_trajectory_nodes (
    id                 BIGSERIAL PRIMARY KEY,
    run_id             BIGINT NOT NULL REFERENCES alphaln_trajectory_runs(id) ON DELETE CASCADE,
    parent_id          BIGINT REFERENCES alphaln_trajectory_nodes(id) ON DELETE CASCADE,
    depth              INTEGER NOT NULL DEFAULT 0,
    action_hash        TEXT NOT NULL,          -- sha256 of the utterance/action tried
    action_summary     TEXT,                   -- short label (no raw PII)
    visits             INTEGER NOT NULL DEFAULT 0,
    value_sum          NUMERIC(10,3) NOT NULL DEFAULT 0,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alphaln_traj_nodes_run
    ON alphaln_trajectory_nodes(run_id, depth ASC);

COMMENT ON TABLE alphaln_trajectory_runs IS
    'AlphaLN Slice 6 trajectory-search runs (MCTS skeleton). Dark until flag flips.';

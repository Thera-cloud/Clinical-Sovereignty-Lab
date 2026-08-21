-- Migration 423: AlphaLN Slice 5 — Sim gym control panel
--
-- Wraps the existing `nate_clinical_bakeoff_engine` under the AlphaLN admin
-- surface. This table records admin-triggered gym runs (audit trail) — the
-- actual match rows still live in the existing `nate_clinical_*` schema.
--
-- Feature flag: ENABLE_ALPHALN_GYM (default false).

CREATE TABLE IF NOT EXISTS alphaln_gym_runs (
    id                 BIGSERIAL PRIMARY KEY,
    admin_user         TEXT NOT NULL,          -- users.username who triggered
    triggered_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at       TIMESTAMPTZ,
    status             TEXT NOT NULL DEFAULT 'queued'
                       CHECK (status IN ('queued','running','complete','error','flag_off')),
    max_matches        INTEGER NOT NULL DEFAULT 4,
    matches_attempted  INTEGER NOT NULL DEFAULT 0,
    matches_complete   INTEGER NOT NULL DEFAULT 0,
    preferences_written INTEGER NOT NULL DEFAULT 0,
    error_text         TEXT,
    result_summary     JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata           JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_alphaln_gym_runs_triggered
    ON alphaln_gym_runs(triggered_at DESC);
CREATE INDEX IF NOT EXISTS idx_alphaln_gym_runs_admin
    ON alphaln_gym_runs(admin_user, triggered_at DESC);

COMMENT ON TABLE alphaln_gym_runs IS
    'AlphaLN Slice 5 admin-triggered bakeoff run audit trail. Actual matches in nate_clinical_bakeoff_matches.';

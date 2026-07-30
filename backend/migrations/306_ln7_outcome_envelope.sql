-- Unified outcome envelope (flywheel Phase E1 / W7).
-- QUANTUM-CRYSTAL-ARCH
-- Additive only. Do NOT reuse 304 (authored-license backfill).

CREATE TABLE IF NOT EXISTS outcome_envelope (
    envelope_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    loop_name           TEXT NOT NULL,
    event_kind          TEXT NOT NULL,
    revision_id         TEXT,
    task_hash           TEXT,
    patch_hash          TEXT,
    domain_tag          TEXT,
    source_node         TEXT,
    burst_id            TEXT,
    attribution_json    JSONB NOT NULL DEFAULT '{}'::jsonb,
    metrics_json        JSONB NOT NULL DEFAULT '{}'::jsonb,
    provenance_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    shadow_outcome      JSONB,
    confounded          BOOLEAN NOT NULL DEFAULT FALSE,
    cost_usd            NUMERIC(12, 6),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_outcome_envelope_loop
    ON outcome_envelope (loop_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_outcome_envelope_rev
    ON outcome_envelope (revision_id)
    WHERE revision_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_outcome_envelope_burst
    ON outcome_envelope (burst_id)
    WHERE burst_id IS NOT NULL;

ALTER TABLE ln7_coding_outcomes
    ADD COLUMN IF NOT EXISTS envelope_id UUID;

CREATE INDEX IF NOT EXISTS idx_ln7_outcomes_envelope
    ON ln7_coding_outcomes (envelope_id)
    WHERE envelope_id IS NOT NULL;

-- Laplace-smoothed adapter win rate for domain routing (B1).
CREATE OR REPLACE VIEW ln7_adapter_win_rate AS
SELECT
    revision_id,
    COUNT(*)::INT AS n,
    SUM(CASE WHEN passed THEN 1 ELSE 0 END)::INT AS wins,
    ((SUM(CASE WHEN passed THEN 1 ELSE 0 END)::NUMERIC + 1.0)
        / (COUNT(*)::NUMERIC + 2.0)) AS smoothed_win_rate
FROM ln7_coding_outcomes
WHERE revision_id IS NOT NULL
  AND created_at > NOW() - INTERVAL '90 days'
GROUP BY revision_id;

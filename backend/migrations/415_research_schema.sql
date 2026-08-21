-- Migration 415: Research schema separation (Slice 5 of Bee HIV+ privacy plan)
--
-- Per BAA §8.7A and HIPAA de-identification requirements, aggregate research
-- datasets must live in a schema that has NO FKs into `public` and NO joins
-- to identified PHI (no user_id UUIDs, no hardware_ids, no free text).
--
-- Only stable pseudonyms (HMAC-SHA256 of user_id, keyed by RESEARCH_HMAC_KEY)
-- appear in `research.*`. The pseudonym function is deterministic across
-- days so longitudinal patterns can be studied, but the mapping is not
-- stored anywhere in this schema — recovering identity requires the HMAC
-- key, which lives outside the DB.
--
-- Flag off = zero effect. No agent populates these tables until
-- ENABLE_RESEARCH_AGGREGATION is set on GREEN.

CREATE SCHEMA IF NOT EXISTS research;

COMMENT ON SCHEMA research IS
    'De-identified aggregate research datasets. NO PHI, NO free text, NO FKs to public. Pseudonyms only.';

-- ---------------------------------------------------------------------------
-- research.metrics_daily — one row per (pseudonym, UTC day)
-- Aggregates public.nevedal_metrics without carrying user_id.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS research.metrics_daily (
    id             BIGSERIAL PRIMARY KEY,
    pseudonym      TEXT NOT NULL,                     -- HMAC(user_id, key), 64 hex chars
    day            DATE NOT NULL,                     -- UTC day bucket
    sample_count   INTEGER NOT NULL,
    c_emo_avg      DECIMAL(6,5),
    c_emo_min      DECIMAL(6,5),
    c_emo_max      DECIMAL(6,5),
    cee_windows    INTEGER DEFAULT 0,
    domain_tag     TEXT,                              -- optional cohort tag (e.g. 'general', 'bee_hiv_plus')
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT metrics_daily_uq UNIQUE (pseudonym, day, domain_tag)
);

CREATE INDEX IF NOT EXISTS idx_metrics_daily_day ON research.metrics_daily(day);
CREATE INDEX IF NOT EXISTS idx_metrics_daily_domain ON research.metrics_daily(domain_tag);

COMMENT ON TABLE research.metrics_daily IS
    'De-identified daily Nevedal C_emo aggregates. Pseudonym is HMAC-SHA256 of user_id.';

-- ---------------------------------------------------------------------------
-- research.crystal_stats_daily — crystal creation counts per domain per day
-- No user_id, no crystal text, no program_id (per-program stats stay in public).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS research.crystal_stats_daily (
    id                 BIGSERIAL PRIMARY KEY,
    day                DATE NOT NULL,
    domain             TEXT NOT NULL,
    crystals_created   INTEGER NOT NULL DEFAULT 0,
    crystals_superseded INTEGER NOT NULL DEFAULT 0,
    avg_confidence     DECIMAL(6,5),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT crystal_stats_daily_uq UNIQUE (day, domain)
);

CREATE INDEX IF NOT EXISTS idx_crystal_stats_daily_day ON research.crystal_stats_daily(day);

COMMENT ON TABLE research.crystal_stats_daily IS
    'De-identified daily crystal creation stats by domain. No pseudonyms — global counts only.';

-- ---------------------------------------------------------------------------
-- research.aggregation_log — audit trail for the aggregator itself
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS research.aggregation_log (
    id            BIGSERIAL PRIMARY KEY,
    run_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    day_processed DATE NOT NULL,
    dataset       TEXT NOT NULL,              -- 'metrics_daily' | 'crystal_stats_daily'
    rows_written  INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL,              -- 'ok' | 'error' | 'skipped'
    detail        TEXT
);

CREATE INDEX IF NOT EXISTS idx_agg_log_run ON research.aggregation_log(run_at DESC);

COMMENT ON TABLE research.aggregation_log IS
    'Audit log for research aggregation runs. Append-only; retained indefinitely.';

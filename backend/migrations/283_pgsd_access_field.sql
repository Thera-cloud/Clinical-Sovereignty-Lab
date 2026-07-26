-- QUANTUM-CRYSTAL-ARCH — PGSD access substrate + field schema (additive)
-- Canonical user_id remains hardware_id (matches 191 + admin tab).
-- username is additive for conversation_history joins.

-- ─── Identity: username on existing snapshots ─────────────────────────
ALTER TABLE pgsd_snapshots
    ADD COLUMN IF NOT EXISTS username VARCHAR;

UPDATE pgsd_snapshots s
SET username = u.username
FROM users u
WHERE s.username IS NULL
  AND (s.user_id = u.hardware_id OR s.user_id = u.username OR s.user_id = u.id::text);

CREATE INDEX IF NOT EXISTS idx_pgsd_snapshots_username
    ON pgsd_snapshots (username)
    WHERE username IS NOT NULL;

ALTER TABLE pgsd_snapshots
    ADD COLUMN IF NOT EXISTS trigger_source VARCHAR;
ALTER TABLE pgsd_snapshots
    ADD COLUMN IF NOT EXISTS tau_step DOUBLE PRECISION;

-- ─── Crystal PGSD stamps ──────────────────────────────────────────────
ALTER TABLE nate_intelligence_crystals
    ADD COLUMN IF NOT EXISTS pgsd_d1 DOUBLE PRECISION;
ALTER TABLE nate_intelligence_crystals
    ADD COLUMN IF NOT EXISTS pgsd_d2 DOUBLE PRECISION;
ALTER TABLE nate_intelligence_crystals
    ADD COLUMN IF NOT EXISTS pgsd_d3 DOUBLE PRECISION;
ALTER TABLE nate_intelligence_crystals
    ADD COLUMN IF NOT EXISTS pgsd_d4 DOUBLE PRECISION;
ALTER TABLE nate_intelligence_crystals
    ADD COLUMN IF NOT EXISTS pgsd_d5 DOUBLE PRECISION;
ALTER TABLE nate_intelligence_crystals
    ADD COLUMN IF NOT EXISTS pgsd_fingerprint VARCHAR(16);
ALTER TABLE nate_intelligence_crystals
    ADD COLUMN IF NOT EXISTS pgsd_coherence DOUBLE PRECISION;
ALTER TABLE nate_intelligence_crystals
    ADD COLUMN IF NOT EXISTS pgsd_snapshot_id INTEGER;

-- ─── Crisis / PMB regions ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pgsd_crisis_regions (
    id              SERIAL PRIMARY KEY,
    user_id         VARCHAR NOT NULL,
    username        VARCHAR,
    d1_valence      DOUBLE PRECISION,
    d2_arousal      DOUBLE PRECISION,
    d3_relational   DOUBLE PRECISION,
    d4_temporal     DOUBLE PRECISION,
    d5_integration  DOUBLE PRECISION,
    radius          DOUBLE PRECISION DEFAULT 0.25,
    source_event_id VARCHAR,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pgsd_crisis_regions_user
    ON pgsd_crisis_regions (user_id, created_at DESC);

-- ─── Chat correlation (redacted — no full transcript) ─────────────────
CREATE TABLE IF NOT EXISTS pgsd_chat_correlation (
    id              SERIAL PRIMARY KEY,
    user_id         VARCHAR NOT NULL,
    username        VARCHAR,
    snapshot_id     INTEGER,
    surface         VARCHAR NOT NULL,
    session_id      VARCHAR,
    turn_created_at TIMESTAMPTZ,
    text_prefix     VARCHAR(32),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pgsd_chat_corr_user
    ON pgsd_chat_correlation (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pgsd_chat_corr_snap
    ON pgsd_chat_correlation (snapshot_id);

-- ─── Discernment scores ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pgsd_discernment_scores (
    id              SERIAL PRIMARY KEY,
    user_id         VARCHAR NOT NULL,
    username        VARCHAR,
    score_past      DOUBLE PRECISION,
    score_present   DOUBLE PRECISION,
    score_future    DOUBLE PRECISION,
    score_composite DOUBLE PRECISION,
    claim_count     INTEGER DEFAULT 0,
    evidence_json   JSONB,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pgsd_discern_user
    ON pgsd_discernment_scores (user_id, computed_at DESC);

-- ─── Cross-domain agreement ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pgsd_cross_domain_agreement (
    id              SERIAL PRIMARY KEY,
    user_id         VARCHAR NOT NULL,
    username        VARCHAR,
    window_start    TIMESTAMPTZ,
    window_end      TIMESTAMPTZ,
    surfaces        JSONB,
    agreement_score DOUBLE PRECISION,
    detail_json     JSONB,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pgsd_xdomain_user
    ON pgsd_cross_domain_agreement (user_id, computed_at DESC);

-- ─── Trauma wells ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pgsd_trauma_wells (
    id              SERIAL PRIMARY KEY,
    user_id         VARCHAR NOT NULL,
    username        VARCHAR,
    temporal_class  VARCHAR NOT NULL,  -- past | present | future | inherited
    d1_valence      DOUBLE PRECISION,
    d2_arousal      DOUBLE PRECISION,
    d3_relational   DOUBLE PRECISION,
    d4_temporal     DOUBLE PRECISION,
    d5_integration  DOUBLE PRECISION,
    depth           DOUBLE PRECISION,
    source_tag      VARCHAR,
    collapsed       BOOLEAN NOT NULL DEFAULT FALSE,
    meta_json       JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pgsd_wells_user
    ON pgsd_trauma_wells (user_id, temporal_class);

-- ─── Forecasts + Brier ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pgsd_forecasts (
    id              SERIAL PRIMARY KEY,
    user_id         VARCHAR NOT NULL,
    username        VARCHAR,
    forecast_at     TIMESTAMPTZ NOT NULL,
    horizon_hours   INTEGER NOT NULL,
    predicted_json  JSONB NOT NULL,
    realized_json   JSONB,
    brier_score     DOUBLE PRECISION,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pgsd_forecasts_user
    ON pgsd_forecasts (user_id, forecast_at DESC);

-- ─── Field couplings / spectrum / ground state ────────────────────────
CREATE TABLE IF NOT EXISTS pgsd_field_couplings (
    id              SERIAL PRIMARY KEY,
    family_id       VARCHAR,
    member_a        VARCHAR NOT NULL,
    member_b        VARCHAR NOT NULL,
    j_eff           DOUBLE PRECISION,
    h_eff           DOUBLE PRECISION,
    g_control       DOUBLE PRECISION,
    meta_json       JSONB,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pgsd_field_spectrum (
    id              SERIAL PRIMARY KEY,
    user_id         VARCHAR,
    family_id       VARCHAR,
    eigenvalues     JSONB,
    ground_energy   DOUBLE PRECISION,
    gap             DOUBLE PRECISION,
    g_control       DOUBLE PRECISION,
    meta_json       JSONB,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pgsd_ground_states (
    id              SERIAL PRIMARY KEY,
    user_id         VARCHAR NOT NULL,
    username        VARCHAR,
    ground_energy   DOUBLE PRECISION,
    ground_coords   JSONB,
    prior_energy    DOUBLE PRECISION,
    relocation      DOUBLE PRECISION,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pgsd_ground_user
    ON pgsd_ground_states (user_id, computed_at DESC);

CREATE TABLE IF NOT EXISTS pgsd_hamiltonian_track (
    id              SERIAL PRIMARY KEY,
    user_id         VARCHAR NOT NULL,
    username        VARCHAR,
    snapshot_id     INTEGER,
    fidelity        DOUBLE PRECISION,
    tau_delta       DOUBLE PRECISION,
    h_params        JSONB,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pgsd_legacy_string (
    id              SERIAL PRIMARY KEY,
    user_id         VARCHAR NOT NULL,
    username        VARCHAR,
    lineage_json    JSONB,
    inherited_wells INTEGER DEFAULT 0,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

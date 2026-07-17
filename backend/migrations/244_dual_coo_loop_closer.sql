-- QUANTUM-CRYSTAL-ARCH: Dual-COO loop closer — briefs, prior-art, events, clinical CEO apply

CREATE TABLE IF NOT EXISTS coach_insight_briefs (
    id              BIGSERIAL PRIMARY KEY,
    client_user_id  TEXT NOT NULL,
    coach_user_id   TEXT,
    source          VARCHAR(64) NOT NULL,
    title           TEXT NOT NULL,
    body            TEXT NOT NULL,
    risk_class      VARCHAR(16) NOT NULL DEFAULT 'YELLOW',
    status          VARCHAR(32) NOT NULL DEFAULT 'queued',
    task_id         TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_coach_insight_briefs_client
    ON coach_insight_briefs (client_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_coach_insight_briefs_status
    ON coach_insight_briefs (status, created_at DESC);

COMMENT ON TABLE coach_insight_briefs IS
    'Dual-COO insight_route: PMB/Nevedal/SkyEye → coach pre-session briefs (YELLOW until delivered).';

CREATE TABLE IF NOT EXISTS prior_art_sweep_log (
    id              BIGSERIAL PRIMARY KEY,
    query_text      TEXT NOT NULL,
    crystal_id      INTEGER,
    family_id       TEXT,
    hits_json       JSONB NOT NULL DEFAULT '[]'::jsonb,
    status          VARCHAR(32) NOT NULL DEFAULT 'proposed',
    risk_class      VARCHAR(16) NOT NULL DEFAULT 'YELLOW',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_prior_art_sweep_created
    ON prior_art_sweep_log (created_at DESC);

CREATE TABLE IF NOT EXISTS dual_coo_loop_events (
    id              BIGSERIAL PRIMARY KEY,
    kind            VARCHAR(64) NOT NULL,
    risk_class      VARCHAR(16) NOT NULL DEFAULT 'GREEN',
    detail          TEXT,
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dual_coo_loop_events_kind
    ON dual_coo_loop_events (kind, created_at DESC);

CREATE TABLE IF NOT EXISTS ceo_clinical_apply_approvals (
    id              BIGSERIAL PRIMARY KEY,
    shadow_id       BIGINT REFERENCES crystal_confidence_shadow(id) ON DELETE SET NULL,
    crystal_id      INTEGER NOT NULL REFERENCES nate_intelligence_crystals(id) ON DELETE CASCADE,
    domain          VARCHAR(50),
    old_confidence  REAL,
    new_confidence  REAL,
    delta           NUMERIC(6,4) NOT NULL,
    approved_by     TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ceo_clinical_apply_created
    ON ceo_clinical_apply_approvals (created_at DESC);

-- Trust baseline: Dual-COO CEO API checks (additive row)
INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES (
    'ceo_dual_coo_check_count',
    '{"expected": 6, "description": "CEO Dual-COO inbox + clinical apply + patent approve endpoints"}'::jsonb
)
ON CONFLICT (parameter_key) DO UPDATE
SET parameter_value = EXCLUDED.parameter_value;

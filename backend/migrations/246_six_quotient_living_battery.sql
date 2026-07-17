-- Migration 246: Living Battery v5 — scenario bank, standards index, IRT, multi-turn, judge gold
-- Additive only. Draft scenarios stay inert until status='approved'.

CREATE TABLE IF NOT EXISTS six_quotient_scenario_bank (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_key        VARCHAR(64) NOT NULL UNIQUE,
    section             VARCHAR(8) NOT NULL,
    title               TEXT NOT NULL DEFAULT '',
    rubric_focus        TEXT NOT NULL DEFAULT '',
    client_says         TEXT NOT NULL DEFAULT '',
    -- multi-turn: ordered client beats after opening (JSONB array of strings)
    client_beats        JSONB NOT NULL DEFAULT '[]'::jsonb,
    dojo_persona        VARCHAR(32) NOT NULL DEFAULT 'SKEPTIC',
    difficulty_nominal  REAL NOT NULL DEFAULT 0.5,
    -- IRT 2PL (calibrated from external scores; defaults = uninformative)
    irt_a               REAL NOT NULL DEFAULT 1.0,
    irt_b               REAL NOT NULL DEFAULT 0.0,
    discrimination_n    INT NOT NULL DEFAULT 0,
    status              VARCHAR(32) NOT NULL DEFAULT 'draft',
    -- draft | pending_review | approved | retired | rejected
    source              VARCHAR(64) NOT NULL DEFAULT 'v4_anchor',
    -- v4_anchor | generated | external_import | boundary_search
    provenance_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    standards_refs      JSONB NOT NULL DEFAULT '[]'::jsonb,
    safety_flags        JSONB NOT NULL DEFAULT '[]'::jsonb,
    approved_by         VARCHAR(128) DEFAULT '',
    approved_at         TIMESTAMPTZ,
    times_administered  INT NOT NULL DEFAULT 0,
    mean_total_score    REAL,
    pass_rate           REAL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT sq_bank_status_chk CHECK (
        status IN ('draft', 'pending_review', 'approved', 'retired', 'rejected')
    ),
    CONSTRAINT sq_bank_section_chk CHECK (
        section IN ('IQ', 'EQ', 'MQ', 'SQ', 'CQ', 'AQ')
    )
);

CREATE INDEX IF NOT EXISTS idx_sq_bank_status_section
    ON six_quotient_scenario_bank (status, section);
CREATE INDEX IF NOT EXISTS idx_sq_bank_irt_b
    ON six_quotient_scenario_bank (irt_b);

CREATE TABLE IF NOT EXISTS six_quotient_standards_items (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quotient            VARCHAR(8) NOT NULL,
    source_key          VARCHAR(64) NOT NULL,
    source_name         TEXT NOT NULL DEFAULT '',
    title               TEXT NOT NULL DEFAULT '',
    url                 TEXT NOT NULL DEFAULT '',
    published_year      INT,
    authority_tier      SMALLINT NOT NULL DEFAULT 2,
    -- 1=gov/professional body, 2=peer-reviewed, 3=secondary
    summary             TEXT NOT NULL DEFAULT '',
    content_hash        VARCHAR(64) NOT NULL DEFAULT '',
    crystal_id          UUID,
    status              VARCHAR(32) NOT NULL DEFAULT 'pending_review',
    -- pending_review | approved | rejected | superseded
    supersedes_id       UUID,
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_by         VARCHAR(128) DEFAULT '',
    approved_at         TIMESTAMPTZ,
    metadata_json       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT sq_std_quotient_chk CHECK (
        quotient IN ('IQ', 'EQ', 'MQ', 'SQ', 'CQ', 'AQ')
    ),
    CONSTRAINT sq_std_status_chk CHECK (
        status IN ('pending_review', 'approved', 'rejected', 'superseded')
    ),
    UNIQUE (content_hash)
);

CREATE INDEX IF NOT EXISTS idx_sq_std_quotient_status
    ON six_quotient_standards_items (quotient, status);
CREATE INDEX IF NOT EXISTS idx_sq_std_year
    ON six_quotient_standards_items (published_year DESC NULLS LAST);

CREATE TABLE IF NOT EXISTS six_quotient_multi_turn_transcripts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id              UUID NOT NULL REFERENCES six_quotient_runs(id) ON DELETE CASCADE,
    scenario_key        VARCHAR(64) NOT NULL,
    section             VARCHAR(8) NOT NULL,
    turns_json          JSONB NOT NULL DEFAULT '[]'::jsonb,
    process_metrics     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sq_mt_run
    ON six_quotient_multi_turn_transcripts (run_id);

CREATE TABLE IF NOT EXISTS six_quotient_judge_calibrations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    evaluator_id        VARCHAR(128) NOT NULL,
    gold_set_version    VARCHAR(32) NOT NULL DEFAULT 'v1',
    kappa               REAL,
    agreement_rate      REAL,
    n_items             INT NOT NULL DEFAULT 0,
    passed              BOOLEAN NOT NULL DEFAULT FALSE,
    details_json        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sq_judge_eval
    ON six_quotient_judge_calibrations (evaluator_id, created_at DESC);

-- Extend scores scenario_id width for bank keys (v5-AQ-xxxx)
ALTER TABLE six_quotient_scores
    ALTER COLUMN scenario_id TYPE VARCHAR(64);

-- Ability estimate cache per environment (for CAT)
CREATE TABLE IF NOT EXISTS six_quotient_ability_state (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    environment         VARCHAR(32) NOT NULL DEFAULT 'staging',
    theta               REAL NOT NULL DEFAULT 0.0,
    theta_by_section    JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_run_id         UUID,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (environment)
);

INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES (
    'six_quotient_battery_check_count',
    '{"expected": 12, "description": "Six-Quotient Living Battery health + bank + standards checks"}'::jsonb
)
ON CONFLICT (parameter_key) DO UPDATE
SET parameter_value = EXCLUDED.parameter_value;

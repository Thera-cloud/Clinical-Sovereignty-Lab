-- QUANTUM-CRYSTAL-ARCH: L5 observe sandbox — isolated from live soft-rule path
-- Read/observe L4 events; self-adapt ONLY inside these tables.
-- NEVER writes ln_rule_store / clinical runtime gate. Soft classes metadata only.

CREATE TABLE IF NOT EXISTS l5_observe_event (
    id              BIGSERIAL PRIMARY KEY,
    event           TEXT NOT NULL,
    gate_class      TEXT NOT NULL DEFAULT '',
    rule_key        TEXT NOT NULL DEFAULT '',
    version         INTEGER NOT NULL DEFAULT 0,
    detail          TEXT,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_l5_observe_event_at
    ON l5_observe_event (recorded_at DESC);

CREATE INDEX IF NOT EXISTS idx_l5_observe_event_class
    ON l5_observe_event (gate_class, recorded_at DESC)
    WHERE gate_class <> '';

COMMENT ON TABLE l5_observe_event IS
    'L5 sandbox — append-only observation of L4 rule-loop events. Read path for '
    'learning; never consulted by clinical runtime gate or ln_rule_loop apply.';

CREATE TABLE IF NOT EXISTS l5_observe_hypothesis (
    id              BIGSERIAL PRIMARY KEY,
    hypothesis_key  TEXT NOT NULL,
    version         INTEGER NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'observe'
                    CHECK (status IN ('observe', 'adapt_shadow', 'archived')),
    condition_json  JSONB NOT NULL DEFAULT '{}'::jsonb,
    action_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    parent_rule_key TEXT NOT NULL DEFAULT '',
    score           REAL NOT NULL DEFAULT 0.0
                    CHECK (score >= 0.0 AND score <= 1.0),
    sample_n        INTEGER NOT NULL DEFAULT 0,
    created_by      TEXT NOT NULL DEFAULT 'l5_adaptor',
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (hypothesis_key, version)
);

CREATE INDEX IF NOT EXISTS idx_l5_hypothesis_status
    ON l5_observe_hypothesis (status, updated_at DESC);

COMMENT ON TABLE l5_observe_hypothesis IS
    'L5 sandbox — self-adapt hypotheses. status=adapt_shadow scores against '
    'observed L4 shadows only. Promotion into ln_rule_store is FORBIDDEN in code.';

CREATE TABLE IF NOT EXISTS l5_observe_audit (
    id              BIGSERIAL PRIMARY KEY,
    hypothesis_key  TEXT NOT NULL DEFAULT '',
    version         INTEGER NOT NULL DEFAULT 0,
    action          TEXT NOT NULL
                    CHECK (action IN (
                        'observe', 'adapt', 'score', 'archive', 'gate_refuse'
                    )),
    detail          TEXT,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

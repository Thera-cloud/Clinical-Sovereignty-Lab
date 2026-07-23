-- QUANTUM-CRYSTAL-ARCH: LN Sandbox DOJO — unsupervised practice corpus + promotion wall
-- Engineering track + clinical strategy track. Draft learnings never auto-promote to prod recall.

CREATE TABLE IF NOT EXISTS ln_sandbox_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    track           VARCHAR(32) NOT NULL
        CHECK (track IN ('clinical_strategy', 'engineering', 'client_prep')),
    trigger_reason  VARCHAR(64) NOT NULL DEFAULT 'scheduled'
        CHECK (trigger_reason IN ('scheduled', 'idle_window', 'manual', 'ci_fixture')),
    status          VARCHAR(24) NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'failed', 'aborted')),
    task_key        TEXT,
    target_user_id  VARCHAR(64),
    attempts        INT NOT NULL DEFAULT 0,
    best_score      REAL,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_ln_sandbox_sessions_track_started
    ON ln_sandbox_sessions (track, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_ln_sandbox_sessions_target
    ON ln_sandbox_sessions (target_user_id)
    WHERE target_user_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS ln_sandbox_attempts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES ln_sandbox_sessions(id) ON DELETE CASCADE,
    attempt_n       INT NOT NULL,
    prompt_excerpt  TEXT,
    response_text   TEXT,
    score           REAL,
    passed          BOOLEAN NOT NULL DEFAULT FALSE,
    failure_notes   TEXT,
    judge_meta      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (session_id, attempt_n)
);

CREATE INDEX IF NOT EXISTS idx_ln_sandbox_attempts_session
    ON ln_sandbox_attempts (session_id, attempt_n);

-- Practice corpus = sandbox memory. Not production crystals until promoted.
CREATE TABLE IF NOT EXISTS ln_sandbox_practice_corpus (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    track           VARCHAR(32) NOT NULL
        CHECK (track IN ('clinical_strategy', 'engineering', 'client_prep', 'restraint_ref')),
    kind            VARCHAR(48) NOT NULL DEFAULT 'outcome'
        CHECK (kind IN (
            'outcome', 'technique_pattern', 'success_pattern',
            'failure_lesson', 'client_prep', 'restraint_ref'
        )),
    title           TEXT NOT NULL,
    body            TEXT NOT NULL,
    score           REAL,
    confidence      REAL NOT NULL DEFAULT 0.40
        CHECK (confidence >= 0 AND confidence <= 1),
    scope           VARCHAR(80) NOT NULL DEFAULT 'admin_only',
    target_user_id  VARCHAR(64),
    session_id      UUID REFERENCES ln_sandbox_sessions(id) ON DELETE SET NULL,
    origin_surface  VARCHAR(48) NOT NULL DEFAULT 'ln_sandbox',
    tags            JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    status          VARCHAR(24) NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'queued', 'promoted', 'rejected', 'archived')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ln_sandbox_corpus_status
    ON ln_sandbox_practice_corpus (status, track, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ln_sandbox_corpus_user
    ON ln_sandbox_practice_corpus (target_user_id)
    WHERE target_user_id IS NOT NULL AND status IN ('draft', 'queued', 'promoted');
CREATE INDEX IF NOT EXISTS idx_ln_sandbox_corpus_fts
    ON ln_sandbox_practice_corpus
    USING gin (to_tsvector('english', coalesce(title, '') || ' ' || coalesce(body, '')));

CREATE TABLE IF NOT EXISTS ln_sandbox_promotion_queue (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    corpus_id       UUID NOT NULL REFERENCES ln_sandbox_practice_corpus(id) ON DELETE CASCADE,
    requested_by    VARCHAR(64) NOT NULL DEFAULT 'system',
    decision        VARCHAR(24) NOT NULL DEFAULT 'pending'
        CHECK (decision IN ('pending', 'approved', 'rejected')),
    decided_by      VARCHAR(64),
    decision_notes  TEXT,
    crystal_id      BIGINT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_at      TIMESTAMPTZ,
    UNIQUE (corpus_id)
);

CREATE INDEX IF NOT EXISTS idx_ln_sandbox_promo_pending
    ON ln_sandbox_promotion_queue (decision, created_at DESC)
    WHERE decision = 'pending';

-- Seed restraint references (safety corpus — never overwritten by practice wins)
INSERT INTO ln_sandbox_practice_corpus (
    track, kind, title, body, confidence, scope, origin_surface, status, tags, metadata
)
SELECT * FROM (VALUES
(
    'restraint_ref'::varchar,
    'restraint_ref'::varchar,
    'Crisis protocol always wins at live boundary'::text,
    ('Sandbox practice may explore technique variants. Live client turns remain gated by crisis protocol, '
     'Predictive Restraint (MASKED / escalation velocity / surveillance), symbolic verifier, and Sensitive Bridge. '
     'A high sandbox score never bypasses these restraints.')::text,
    0.95::real,
    'admin_only'::varchar,
    'ln_sandbox_restraint'::varchar,
    'promoted'::varchar,
    '["restraint","crisis","live_boundary"]'::jsonb,
    '{"source_doc":"docs/CRISIS_PROTOCOL_ONE_PAGE.md","immutable":true}'::jsonb
),
(
    'restraint_ref'::varchar,
    'restraint_ref'::varchar,
    'No auto-promotion from sandbox to production crystals'::text,
    ('Practice corpus entries stay draft/queued until admin or coach approves via promotion queue. '
     'Promotion writes crystals with origin_surface=ln_sandbox_promoted and must pass NateResponseValidator. '
     'Self-determined success is valid for exploration only.')::text,
    0.95::real,
    'admin_only'::varchar,
    'ln_sandbox_restraint'::varchar,
    'promoted'::varchar,
    '["restraint","promotion","validator"]'::jsonb,
    '{"immutable":true}'::jsonb
)
) AS v(track, kind, title, body, confidence, scope, origin_surface, status, tags, metadata)
WHERE NOT EXISTS (
    SELECT 1 FROM ln_sandbox_practice_corpus c
    WHERE c.track = 'restraint_ref' AND c.title = v.title
);

COMMENT ON TABLE ln_sandbox_sessions IS
    'LN Sandbox DOJO practice sessions (clinical strategy / engineering / client prep).';
COMMENT ON TABLE ln_sandbox_practice_corpus IS
    'Sandbox memory — draft learnings; production recall only after promotion gate.';
COMMENT ON TABLE ln_sandbox_promotion_queue IS
    'Human gate between practice corpus and nate_intelligence_crystals.';

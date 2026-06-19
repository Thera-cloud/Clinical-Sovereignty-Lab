-- Stance Telemetry + Witness-Loop Auditor (backlog item 10)
-- Additive only. Records one row per stance decision emitted by the LN stance
-- resolver; consumed by the Stance Loop Auditor (3 DB-level checks).

CREATE TABLE IF NOT EXISTS stance_decisions (
    id              BIGSERIAL PRIMARY KEY,
    uid             TEXT,
    turn_index      INT,
    intent          TEXT,
    move            TEXT,
    end_on_question BOOLEAN,
    stripped_menu   BOOLEAN DEFAULT false,
    stripped_opener BOOLEAN DEFAULT false,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stance_decisions_uid_created
    ON stance_decisions (uid, created_at);

-- Trust baseline seed for the Stance Loop Auditor (3 DB checks):
--   1) table_exists, 2) witness_loop_regression, 3) data_health
INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES (
    'stance_loop_check_count',
    '{"expected": 3, "description": "Stance Loop: table exists (1) + witness-loop regression (1) + data health (1)"}'::jsonb
)
ON CONFLICT (parameter_key) DO NOTHING;

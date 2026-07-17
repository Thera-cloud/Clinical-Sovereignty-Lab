-- QUANTUM-CRYSTAL-ARCH: Nate-mediated coach↔client session negotiation (option 1).
-- Coach still decides approve / busy / alt-time; Nate carries the loop.

CREATE TABLE IF NOT EXISTS session_negotiations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      VARCHAR(64) NOT NULL,
    client_id       VARCHAR(128) NOT NULL,
    coach_id        VARCHAR(128) NOT NULL,
    status          VARCHAR(32) NOT NULL DEFAULT 'awaiting_coach',
    -- awaiting_coach | alt_proposed | awaiting_client | approved | declined | busy | expired | cancelled
    proposed_start  TIMESTAMPTZ,
    proposed_end    TIMESTAMPTZ,
    alt_slots       JSONB NOT NULL DEFAULT '[]'::jsonb,
    coach_note      TEXT DEFAULT '',
    client_note     TEXT DEFAULT '',
    round           INTEGER NOT NULL DEFAULT 1,
    max_rounds      INTEGER NOT NULL DEFAULT 3,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_session_negotiations_session
    ON session_negotiations(session_id);
CREATE INDEX IF NOT EXISTS idx_session_negotiations_coach_status
    ON session_negotiations(coach_id, status);
CREATE INDEX IF NOT EXISTS idx_session_negotiations_client_status
    ON session_negotiations(client_id, status);

COMMENT ON TABLE session_negotiations IS
    'Nate-mediated scheduling negotiation; coach retains approve/busy/alt authority.';

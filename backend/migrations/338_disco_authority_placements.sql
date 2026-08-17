-- 338_disco_authority_placements.sql
-- T1.16 placement tracker. Additive. Writes only when DISCO_AUTHORITY=on.

BEGIN;

CREATE TABLE IF NOT EXISTS disco_authority_placements (
    id              BIGSERIAL PRIMARY KEY,
    coach_id        VARCHAR NOT NULL,
    target_id       TEXT NOT NULL,
    target_kind     TEXT NOT NULL,
    packet          JSONB NOT NULL DEFAULT '{}'::jsonb,
    status          TEXT NOT NULL DEFAULT 'drafted'
                    CHECK (status IN ('drafted', 'sent', 'placed', 'rejected')),
    placement_url   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (coach_id, target_id)
);

CREATE INDEX IF NOT EXISTS idx_disco_authority_placements_coach
    ON disco_authority_placements (coach_id);

COMMIT;

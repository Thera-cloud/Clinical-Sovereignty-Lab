-- 431: Studio session tape pointer + episode master/cut keys.
-- LiveKit egress writes studio/{session_id}.mp4 to R2; this stamps PG.
-- Additive only. QUANTUM-CRYSTAL-ARCH

ALTER TABLE studio_sessions
    ADD COLUMN IF NOT EXISTS media_r2_key TEXT,
    ADD COLUMN IF NOT EXISTS egress_id TEXT,
    ADD COLUMN IF NOT EXISTS media_ready BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE studio_episodes
    ADD COLUMN IF NOT EXISTS media_master_r2_key TEXT,
    ADD COLUMN IF NOT EXISTS media_cut_r2_key TEXT;

CREATE INDEX IF NOT EXISTS idx_studio_sessions_egress
    ON studio_sessions (egress_id)
    WHERE egress_id IS NOT NULL;

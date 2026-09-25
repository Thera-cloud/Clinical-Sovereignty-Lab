-- 443: session-scoped editor assets for STUDIO EDIT storyboard (additive).
-- QUANTUM-CRYSTAL-ARCH

CREATE TABLE IF NOT EXISTS studio_episode_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    episode_id UUID NOT NULL REFERENCES studio_episodes(id) ON DELETE CASCADE,
    session_id UUID,
    coach_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'video',
    r2_key TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    bytes INT NOT NULL DEFAULT 0,
    duration_s DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_studio_episode_assets_ep
    ON studio_episode_assets (episode_id, created_at DESC);

ALTER TABLE studio_episode_assets DROP CONSTRAINT IF EXISTS studio_episode_assets_kind_chk;
ALTER TABLE studio_episode_assets ADD CONSTRAINT studio_episode_assets_kind_chk
    CHECK (kind IN ('video', 'audio', 'b-roll', 'commercial'));

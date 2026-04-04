-- Migration 174: SSE Thera-World core data model
-- 5 tables for lifelong journey engine, quests, missions, panel log, admin alerts

CREATE TABLE IF NOT EXISTS sse_user_journeys (
    journey_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    current_biome TEXT NOT NULL DEFAULT 'dark_forest',
    current_phase TEXT NOT NULL DEFAULT 'awakening',
    journey_start TIMESTAMPTZ DEFAULT now(),
    last_panel_at TIMESTAMPTZ,
    panels_generated INT DEFAULT 0,
    dominant_character TEXT DEFAULT 'mirror',
    therapeutic_arc TEXT DEFAULT 'exploration',
    journey_metadata JSONB DEFAULT '{}',
    UNIQUE(user_id)
);

CREATE TABLE IF NOT EXISTS sse_quests (
    quest_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    goal TEXT NOT NULL,
    goal_domain TEXT,
    status TEXT DEFAULT 'active',
    started_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ,
    progress_notes JSONB DEFAULT '[]',
    panels_generated INT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sse_missions (
    mission_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    relationship_target TEXT NOT NULL,
    relationship_type TEXT,
    status TEXT DEFAULT 'active',
    started_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ,
    progress_notes JSONB DEFAULT '[]',
    panels_generated INT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sse_panel_log (
    panel_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    panel_type TEXT NOT NULL,
    source_id UUID,
    source_type TEXT NOT NULL,
    r2_url TEXT,
    prompt_used TEXT,
    biome TEXT,
    character_manifest TEXT,
    narrative_text TEXT,
    panel_tone TEXT,
    crystal_domains_used JSONB DEFAULT '[]',
    generated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sse_admin_alerts (
    alert_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT,
    metadata JSONB DEFAULT '{}',
    acknowledged BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_panel_log_user ON sse_panel_log(user_id, generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_quests_user ON sse_quests(user_id, status);
CREATE INDEX IF NOT EXISTS idx_missions_user ON sse_missions(user_id, status);
CREATE INDEX IF NOT EXISTS idx_admin_alerts ON sse_admin_alerts(acknowledged, created_at DESC);

-- Migration 175: Archetype image URL, story continuity columns, enrollment source tracking
ALTER TABLE sse_identity_forge ADD COLUMN IF NOT EXISTS archetype_image_url TEXT;
ALTER TABLE sse_user_journeys ADD COLUMN IF NOT EXISTS last_panel_summary TEXT;
ALTER TABLE sse_user_journeys ADD COLUMN IF NOT EXISTS last_panel_npcs JSONB DEFAULT '[]';
ALTER TABLE sse_user_journeys ADD COLUMN IF NOT EXISTS panel_sequence INT DEFAULT 0;
ALTER TABLE sse_enrolled_users ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'intake_auto';

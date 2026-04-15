-- Migration 180: Group Entity Video Architecture
-- Creates group_entities, group_entity_members, group_videos tables
-- Links families and corporate_sponsors to group_entities

-- 1. Core group entity table
CREATE TABLE IF NOT EXISTS group_entities (
    group_entity_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_type          VARCHAR(50) NOT NULL,
    group_name          VARCHAR(255),
    lora_folder_path    TEXT,
    scene_context       VARCHAR(100),
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Group membership (references group_entities)
CREATE TABLE IF NOT EXISTS group_entity_members (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_entity_id     UUID REFERENCES group_entities(group_entity_id),
    client_id           UUID NOT NULL,
    joined_at           TIMESTAMPTZ DEFAULT NOW(),
    lora_snapshot_path  TEXT,
    is_active           BOOLEAN DEFAULT TRUE,
    UNIQUE(group_entity_id, client_id)
);

-- 3. Group video generation tracking (references group_entities)
CREATE TABLE IF NOT EXISTS group_videos (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_entity_id     UUID REFERENCES group_entities(group_entity_id),
    month               INT NOT NULL,
    year                INT NOT NULL,
    video_url           TEXT,
    composite_url       TEXT,
    generated_at        TIMESTAMPTZ,
    status              TEXT DEFAULT 'pending',
    error_message       TEXT,
    UNIQUE(group_entity_id, month, year)
);

-- 4. Link families to group_entities
ALTER TABLE families
    ADD COLUMN IF NOT EXISTS group_entity_id UUID REFERENCES group_entities(group_entity_id);

-- 5. Link corporate_sponsors to group_entities
ALTER TABLE corporate_sponsors
    ADD COLUMN IF NOT EXISTS group_entity_id UUID REFERENCES group_entities(group_entity_id);

-- 6. Indexes
CREATE INDEX IF NOT EXISTS idx_group_entity_members_group
    ON group_entity_members(group_entity_id);
CREATE INDEX IF NOT EXISTS idx_group_entity_members_client
    ON group_entity_members(client_id);
CREATE INDEX IF NOT EXISTS idx_group_videos_group_month
    ON group_videos(group_entity_id, year, month);
CREATE INDEX IF NOT EXISTS idx_group_entities_type
    ON group_entities(group_type);

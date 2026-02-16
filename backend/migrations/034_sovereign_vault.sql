-- =============================================================================
-- Migration 034: Sovereign Vault
-- Sovereign Sanctuary — Personal vault for conversations, uploads, reports,
-- transfer crystals, and legacy content.
-- =============================================================================

-- ─── 1. vault_folders ───

CREATE TABLE IF NOT EXISTS vault_folders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id VARCHAR(255) NOT NULL,
    name VARCHAR(64) NOT NULL,
    parent_id UUID REFERENCES vault_folders(id) ON DELETE SET NULL,
    icon VARCHAR(10) DEFAULT '📁',
    color VARCHAR(7),
    is_system BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    item_count INT DEFAULT 0,
    sort_order INT DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_vault_folders_member_id ON vault_folders(member_id);
CREATE INDEX IF NOT EXISTS idx_vault_folders_parent_id ON vault_folders(parent_id);

CREATE TRIGGER vault_folders_updated_at
    BEFORE UPDATE ON vault_folders
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ─── 2. vault_items ───

CREATE TABLE IF NOT EXISTS vault_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id VARCHAR(255) NOT NULL,
    folder_id UUID REFERENCES vault_folders(id) ON DELETE SET NULL,
    content_type VARCHAR(50) NOT NULL,
    filename VARCHAR(255),
    display_name VARCHAR(255) NOT NULL,
    blob_path TEXT,
    thumbnail_path TEXT,
    size_bytes BIGINT DEFAULT 0,
    mime_type VARCHAR(100),
    extracted_text_preview TEXT,
    page_count INT,
    dimensions JSONB,
    duration_seconds FLOAT,
    session_id VARCHAR(255),
    coherence_at_creation FLOAT,
    themes JSONB DEFAULT '[]'::jsonb,
    annotations JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    uploaded_at TIMESTAMPTZ,
    last_accessed_at TIMESTAMPTZ,
    last_discussed_at TIMESTAMPTZ,
    moved_at TIMESTAMPTZ,
    starred BOOLEAN DEFAULT FALSE,
    is_legacy BOOLEAN DEFAULT FALSE,
    is_shared_family BOOLEAN DEFAULT FALSE,
    ttl_seconds INT,
    content_hash VARCHAR(64),
    search_vector TSVECTOR
);

CREATE INDEX IF NOT EXISTS idx_vault_items_member_id ON vault_items(member_id);
CREATE INDEX IF NOT EXISTS idx_vault_items_folder_id ON vault_items(folder_id);
CREATE INDEX IF NOT EXISTS idx_vault_items_content_type ON vault_items(content_type);
CREATE INDEX IF NOT EXISTS idx_vault_items_created_at ON vault_items(created_at);
CREATE INDEX IF NOT EXISTS idx_vault_items_search_vector ON vault_items USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS idx_vault_items_starred ON vault_items(member_id, starred) WHERE starred = TRUE;

-- Trigger: auto-update search_vector on vault_items INSERT/UPDATE
CREATE OR REPLACE FUNCTION vault_items_search_vector_trigger()
RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector := to_tsvector(
        'english',
        coalesce(NEW.display_name, '') || ' ' ||
        coalesce(NEW.filename, '') || ' ' ||
        coalesce(NEW.extracted_text_preview, '')
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER vault_items_search_vector_update
    BEFORE INSERT OR UPDATE OF display_name, filename, extracted_text_preview ON vault_items
    FOR EACH ROW EXECUTE FUNCTION vault_items_search_vector_trigger();

-- ─── 3. transfer_crystals ───

CREATE TABLE IF NOT EXISTS transfer_crystals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id VARCHAR(255) NOT NULL,
    source_platform VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    conversation_count INT DEFAULT 0,
    message_count INT DEFAULT 0,
    date_range_start VARCHAR(50),
    date_range_end VARCHAR(50),
    crystal JSONB NOT NULL DEFAULT '{}'::jsonb,
    version VARCHAR(10) DEFAULT '1.0',
    processing_time_seconds FLOAT,
    token_cost FLOAT DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_transfer_crystals_member_id ON transfer_crystals(member_id);
CREATE INDEX IF NOT EXISTS idx_transfer_crystals_created_at ON transfer_crystals(created_at);

-- ─── 4. vault_activity ───

CREATE TABLE IF NOT EXISTS vault_activity (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id VARCHAR(255) NOT NULL,
    action VARCHAR(50) NOT NULL,
    item_id UUID,
    folder_id UUID,
    metadata JSONB DEFAULT '{}'::jsonb,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vault_activity_member_id ON vault_activity(member_id);
CREATE INDEX IF NOT EXISTS idx_vault_activity_item_id ON vault_activity(item_id);
CREATE INDEX IF NOT EXISTS idx_vault_activity_timestamp ON vault_activity(timestamp);

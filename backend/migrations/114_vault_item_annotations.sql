-- Migration 114: vault_item_annotations
-- Stores Little Nate's photo analysis results, emotional observations,
-- and follow-up Q&A threads for vault items (photos, documents).

CREATE TABLE IF NOT EXISTS vault_item_annotations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vault_item_id UUID NOT NULL REFERENCES vault_items(id) ON DELETE CASCADE,
    user_id VARCHAR(255) NOT NULL,
    annotation_type VARCHAR(50) NOT NULL DEFAULT 'photo_analysis',
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vault_annotations_item ON vault_item_annotations(vault_item_id);
CREATE INDEX IF NOT EXISTS idx_vault_annotations_user ON vault_item_annotations(user_id);
CREATE INDEX IF NOT EXISTS idx_vault_annotations_type ON vault_item_annotations(annotation_type);
CREATE INDEX IF NOT EXISTS idx_vault_annotations_created ON vault_item_annotations(created_at DESC);

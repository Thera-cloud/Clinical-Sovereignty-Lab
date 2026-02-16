-- =============================================================================
-- Migration 037: Transfer Conversation Support
-- Adds index for efficient filtering of imported conversation vault items
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_vault_items_transfer_conv 
    ON vault_items(member_id, content_type) 
    WHERE content_type IN ('transfer_conversation', 'transfer_crystal');

-- Index for deduplication by content hash within member's vault
CREATE INDEX IF NOT EXISTS idx_vault_items_content_hash
    ON vault_items(member_id, content_hash)
    WHERE content_hash IS NOT NULL;

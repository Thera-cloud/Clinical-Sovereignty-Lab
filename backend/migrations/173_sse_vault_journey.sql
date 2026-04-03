-- =============================================================================
-- Migration 173: SSE Vault Journey Integration
-- Indexes for SSE panel queries on vault_items using the dimensions JSONB
-- (which stores SSE metadata including category, expires_at, push flags)
-- =============================================================================

-- Index for finding SSE panels by content_type
CREATE INDEX IF NOT EXISTS idx_vault_items_sse_panel
  ON vault_items (content_type)
  WHERE content_type = 'sse_panel';

-- Index for expiry queries on SSE panels
CREATE INDEX IF NOT EXISTS idx_vault_items_sse_expires
  ON vault_items ((dimensions->>'expires_at'))
  WHERE content_type = 'sse_panel';

-- SSE panel expiry check runs daily at 02:00 UTC via SSEOrchestrator heartbeat

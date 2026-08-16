-- Additive: Workspace calendar pull (Google → Sanctuary busy + Sanctuary event edits).
-- google_workspace_connection lacked incremental-sync columns used by 183 pull.
-- QUANTUM-CRYSTAL-ARCH

ALTER TABLE google_workspace_connection
  ADD COLUMN IF NOT EXISTS target_calendar_id VARCHAR DEFAULT 'primary';
ALTER TABLE google_workspace_connection
  ADD COLUMN IF NOT EXISTS sync_token TEXT;
ALTER TABLE google_workspace_connection
  ADD COLUMN IF NOT EXISTS last_sync_at TIMESTAMPTZ;
ALTER TABLE google_workspace_connection
  ADD COLUMN IF NOT EXISTS last_full_sync_at TIMESTAMPTZ;

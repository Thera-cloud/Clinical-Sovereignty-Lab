-- Additive per-coach LinkedIn tokens (isolated from SkyEye).
CREATE TABLE IF NOT EXISTS coach_linkedin_connection (
    coach_id VARCHAR PRIMARY KEY,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    person_urn TEXT,
    revoked_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE google_workspace_connection
  ADD COLUMN IF NOT EXISTS gmail_history_id TEXT;


-- Migration 328: Google Workspace pairing + voice campaign substrate (Seam 0)
-- Additive only. No column drops. CHECK widen = DROP+ADD.
-- New FKs are hardware_id VARCHAR (no REFERENCES until uq_users_hardware_id exists).
-- Do not encrypt coaching_sessions display columns.

-- ── 0.1 UNIQUE hardware_id (skip if collisions) ────────────────────────────
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM users
    WHERE hardware_id IS NOT NULL AND hardware_id <> ''
    GROUP BY hardware_id HAVING COUNT(*) > 1
  ) THEN
    RAISE NOTICE '328: uq_users_hardware_id skipped — duplicate hardware_id values exist';
  ELSE
    CREATE UNIQUE INDEX IF NOT EXISTS uq_users_hardware_id
      ON users (hardware_id)
      WHERE hardware_id IS NOT NULL AND hardware_id <> '';
  END IF;
END $$;

CREATE OR REPLACE VIEW workspace_identity AS
SELECT hardware_id,
       username,
       id AS user_uuid,
       role
FROM users;

-- ── 4.1 Extend 183 connection (calendar_183 stays username-keyed UNIQUE) ───
ALTER TABLE google_calendar_connection
  ADD COLUMN IF NOT EXISTS consent_recorded_at TIMESTAMPTZ;
ALTER TABLE google_calendar_connection
  ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ;
ALTER TABLE google_calendar_connection
  ADD COLUMN IF NOT EXISTS chat_webhook_url TEXT;
ALTER TABLE google_calendar_connection
  ADD COLUMN IF NOT EXISTS workspace_features JSONB DEFAULT '{}'::jsonb;
ALTER TABLE google_calendar_connection
  ADD COLUMN IF NOT EXISTS token_app TEXT NOT NULL DEFAULT 'calendar_183';

-- Sibling table: coach Workspace tokens (GOOGLE_WS_*). Never mix with 183 refresh tokens.
CREATE TABLE IF NOT EXISTS google_workspace_connection (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR NOT NULL UNIQUE,          -- users.username
    hardware_id VARCHAR NOT NULL,
    user_role VARCHAR NOT NULL CHECK (user_role IN ('COACH','ADMIN')),
    google_email VARCHAR,
    google_user_id VARCHAR,
    access_token TEXT NOT NULL,               -- TokenCipher
    refresh_token TEXT NOT NULL,              -- TokenCipher
    token_expiry TIMESTAMPTZ,
    scopes TEXT,
    token_app TEXT NOT NULL DEFAULT 'workspace_ws',
    consent_recorded_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    chat_webhook_url TEXT,
    workspace_features JSONB DEFAULT '{}'::jsonb,
    error_message TEXT,
    error_count INT DEFAULT 0,
    connected_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_gws_conn_hw ON google_workspace_connection (hardware_id);

-- Unused this push (Gmail History poll, not Pub/Sub watch)
CREATE TABLE IF NOT EXISTS calendar_watch_channels (
    coach_id VARCHAR PRIMARY KEY,
    channel_id TEXT,
    resource_id TEXT,
    expires_at TIMESTAMPTZ
);

-- ── 4.2 Client vault exposure ──────────────────────────────────────────────
ALTER TABLE users ADD COLUMN IF NOT EXISTS vault_sync BOOLEAN DEFAULT false;
ALTER TABLE users ADD COLUMN IF NOT EXISTS app_enabled BOOLEAN DEFAULT true;
ALTER TABLE users ADD COLUMN IF NOT EXISTS relationship_class TEXT DEFAULT 'coaching';
ALTER TABLE users ADD COLUMN IF NOT EXISTS client_jurisdiction TEXT;

-- ── 4.6 Envelope keys + consent ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS client_data_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id VARCHAR NOT NULL,               -- hardware_id
    dek_id UUID NOT NULL DEFAULT gen_random_uuid(),
    wrapped_dek TEXT NOT NULL,                -- client_envelope_cipher KEK wrap
    created_at TIMESTAMPTZ DEFAULT NOW(),
    destroyed_at TIMESTAMPTZ,
    UNIQUE (client_id, dek_id)
);
CREATE INDEX IF NOT EXISTS idx_client_data_keys_client
  ON client_data_keys (client_id) WHERE destroyed_at IS NULL;

CREATE TABLE IF NOT EXISTS consent_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coach_id VARCHAR,
    client_id VARCHAR,
    version TEXT NOT NULL,
    document_ref TEXT,
    recorded_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── 4.4 Drafts / campaigns / engagements ───────────────────────────────────
CREATE TABLE IF NOT EXISTS email_drafts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coach_id VARCHAR NOT NULL,
    client_id VARCHAR,
    draft_type TEXT NOT NULL DEFAULT 'session_followup',
    gmail_draft_id TEXT,
    to_email TEXT,
    subject TEXT,
    body_ciphertext TEXT,                     -- client DEK when client_id set
    status TEXT NOT NULL DEFAULT 'pending'
      CHECK (status IN ('pending','pushed','sent','discarded','blocked')),
    vault_blocked BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_email_drafts_coach ON email_drafts (coach_id, created_at DESC);

CREATE TABLE IF NOT EXISTS coach_marketing_campaigns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coach_id VARCHAR NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    day_n INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE marketing_content
  ADD COLUMN IF NOT EXISTS campaign_id UUID;
ALTER TABLE marketing_content
  ADD COLUMN IF NOT EXISTS post_urn TEXT;
ALTER TABLE marketing_content
  ADD COLUMN IF NOT EXISTS post_url TEXT;
ALTER TABLE marketing_content
  ADD COLUMN IF NOT EXISTS coach_id VARCHAR;

DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN
    SELECT con.conname
    FROM pg_constraint con
    JOIN pg_class rel ON rel.oid = con.conrelid
    WHERE rel.relname = 'marketing_content'
      AND con.contype = 'c'
      AND pg_get_constraintdef(con.oid) ILIKE '%content_type%'
  LOOP
    EXECUTE format('ALTER TABLE marketing_content DROP CONSTRAINT IF EXISTS %I', r.conname);
  END LOOP;
  ALTER TABLE marketing_content ADD CONSTRAINT marketing_content_content_type_check
    CHECK (content_type IN (
      'blog', 'email_drip', 'outreach', 'directory_page',
      'linkedin_post', 'drip_touch', 'newsletter_issue'
    ));
END $$;

CREATE TABLE IF NOT EXISTS campaign_engagements (
    id BIGSERIAL PRIMARY KEY,
    coach_id VARCHAR NOT NULL,
    campaign_id UUID,
    source TEXT,
    actor_handle TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS post_nudges (
    id BIGSERIAL PRIMARY KEY,
    coach_id VARCHAR NOT NULL,
    content_id BIGINT REFERENCES marketing_content(id) ON DELETE CASCADE,
    channel TEXT,
    scheduled_at TIMESTAMPTZ,
    sent_at TIMESTAMPTZ
);

-- ── 4.5 Tasks / supervision (reuse coach_hierarchy; no master_coach role) ──
CREATE TABLE IF NOT EXISTS coach_client_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coach_id VARCHAR NOT NULL,
    client_id VARCHAR NOT NULL,
    assignee_id VARCHAR NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS task_progress (
    id BIGSERIAL PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES coach_client_tasks(id) ON DELETE CASCADE,
    note TEXT,
    recorded_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS care_plan_reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coach_id VARCHAR NOT NULL,
    client_id VARCHAR NOT NULL,
    reviewer_id VARCHAR,
    body TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS supervision_guidance (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    master_coach_id VARCHAR NOT NULL,
    assistant_id VARCHAR NOT NULL,
    body TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS supervision_access_audit (
    id BIGSERIAL PRIMARY KEY,
    actor_id VARCHAR NOT NULL,
    target_id VARCHAR NOT NULL,
    action TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── 4.6 Libraries + clinical registry ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS practice_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coach_id VARCHAR,
    title TEXT NOT NULL,
    body TEXT,
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS org_library (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id VARCHAR,
    title TEXT NOT NULL,
    r2_key TEXT,
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS coach_credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coach_id VARCHAR NOT NULL,
    credential_type TEXT,
    document_ref TEXT,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS legal_holds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id VARCHAR NOT NULL,
    reason TEXT,
    placed_at TIMESTAMPTZ DEFAULT NOW(),
    released_at TIMESTAMPTZ
);

ALTER TABLE nate_intelligence_crystals
  ADD COLUMN IF NOT EXISTS source_type TEXT;

CREATE TABLE IF NOT EXISTS content_topics (
    id BIGSERIAL PRIMARY KEY,
    topic TEXT NOT NULL UNIQUE,
    domain TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

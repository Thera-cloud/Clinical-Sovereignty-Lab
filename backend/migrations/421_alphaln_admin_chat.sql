-- Migration 421: AlphaLN admin twin chat (Slice 0 + 2)
--
-- Additive only. No ALTER on production tables. Namespace `alphaln_*` so it
-- cannot collide with `nate_intelligence_*` (production memory) or
-- `nate_clinical_*` (bakeoff gym).
--
-- Purpose:
--   AlphaLN is a shadow research twin of Little Nate. This migration adds
--   the minimum state required for the admin-only chat surface exposed at
--   /api/admin/alphaln/*. AlphaLN never writes to conversation_history,
--   nate_intelligence_crystals, or nevedal_metrics -- see cursor rule
--   alphaln-twin-isolation.mdc for the full invariants.
--
-- Feature flags (env, default off):
--   ENABLE_ALPHALN_TWIN       -- backend router responds vs 503
--   ENABLE_ALPHALN_ADMIN_UI   -- (client-side, informational only)

CREATE TABLE IF NOT EXISTS alphaln_conversations (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_user   TEXT NOT NULL,          -- users.username of the admin (DrNevedal1 today)
    title        TEXT,                   -- optional short label
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at     TIMESTAMPTZ,
    metadata     JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_alphaln_conversations_admin_created
    ON alphaln_conversations(admin_user, created_at DESC);

CREATE TABLE IF NOT EXISTS alphaln_messages (
    id               BIGSERIAL PRIMARY KEY,
    conversation_id  UUID NOT NULL REFERENCES alphaln_conversations(id) ON DELETE CASCADE,
    role             TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
    content          TEXT NOT NULL,
    provider         TEXT,               -- e.g. 'grok', 'workers_ai'; null for user turns
    latency_ms       INTEGER,
    tokens_used      INTEGER,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata         JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_alphaln_messages_conv_created
    ON alphaln_messages(conversation_id, created_at ASC);

COMMENT ON TABLE alphaln_conversations IS
    'AlphaLN admin twin chat sessions. Admin-only surface, feature-flagged. See cursor rule alphaln-twin-isolation.mdc.';
COMMENT ON TABLE alphaln_messages IS
    'Turn-by-turn transcript for AlphaLN admin chat. Never mirrored into conversation_history.';

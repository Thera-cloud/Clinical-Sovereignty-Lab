-- Migration 427: pgcrypto encryption for alphaln_messages.content
-- =============================================================================
-- Fills gap G4 identified in the AlphaLN twin post-build audit: the admin
-- transcript for the AlphaLN shadow twin was stored plaintext in
-- `alphaln_messages.content`, while every other conversation surface
-- (conversation_history, coaching_sessions, vault_items, etc.) is protected
-- by pgcrypto AES-256 via the trigger pattern from migration 105.
--
-- This migration is ADDITIVE and safe to apply while ENABLE_ALPHALN_TWIN is on
-- or off. It:
--   1. Adds `content_enc BYTEA` shadow column (nullable).
--   2. Installs a BEFORE INSERT/UPDATE trigger that populates content_enc from
--      content using encrypt_pii() (defined in migration 105).
--   3. Backfills existing rows (if any) using the current app.pii_key.
--
-- We intentionally do NOT drop `content` — keeping the plaintext column
-- preserves backward compatibility with the existing router until the app
-- migrates to read `content_enc` via a secure view. This mirrors the
-- conversation_history rollout pattern (migration 105 lines 152-190).
--
-- Follows invariants in .cursor/rules/alphaln-twin-isolation.mdc.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

ALTER TABLE alphaln_messages
    ADD COLUMN IF NOT EXISTS content_enc BYTEA;

COMMENT ON COLUMN alphaln_messages.content_enc IS
    'pgcrypto AES-256 encrypted admin/AlphaLN transcript. Populated by trigger. See migration 427.';

CREATE OR REPLACE FUNCTION alphaln_messages_encrypt_trigger()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
AS $$
BEGIN
    IF NEW.content IS NOT NULL AND NEW.content <> '' THEN
        NEW.content_enc := encrypt_pii(NEW.content);
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_alphaln_messages_encrypt ON alphaln_messages;
CREATE TRIGGER trg_alphaln_messages_encrypt
    BEFORE INSERT OR UPDATE ON alphaln_messages
    FOR EACH ROW
    EXECUTE FUNCTION alphaln_messages_encrypt_trigger();

-- Backfill any existing rows. Safe: encrypt_pii returns NULL if app.pii_key
-- is not set for this session, in which case the row remains plaintext-only
-- and will be re-encrypted on the next UPDATE. This preserves the two-layer
-- pattern from migration 105.
UPDATE alphaln_messages
   SET content = content
 WHERE content_enc IS NULL
   AND content IS NOT NULL
   AND content <> '';

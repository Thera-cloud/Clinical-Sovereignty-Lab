-- Migration 101: PII Encryption Markers
-- Tracks which users have had PII encrypted at the application layer.
-- Actual encryption is done by the backend on read/write using Fernet (AES-128-CBC).

-- Add tracking column: 'true' when email/phone have been encrypted
ALTER TABLE users ADD COLUMN IF NOT EXISTS pii_encrypted BOOLEAN DEFAULT FALSE;

-- Add encryption flag to conversation_history
ALTER TABLE conversation_history ADD COLUMN IF NOT EXISTS content_encrypted BOOLEAN DEFAULT FALSE;

COMMENT ON COLUMN users.pii_encrypted IS 'True when email and phone fields have been Fernet-encrypted at the application layer';
COMMENT ON COLUMN conversation_history.content_encrypted IS 'True when content field has been Fernet-encrypted at the application layer';

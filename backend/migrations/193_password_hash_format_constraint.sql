-- Migration 193: Enforce PBKDF2 salt:hex password_hash format at DB level.
--
-- Rationale: 2026-04-28 zacks99 incident — a manual `UPDATE users SET password_hash = crypt(...)`
-- inserted a bcrypt $2a$... hash that the application's PBKDF2-based verify_password()
-- silently rejected. This CHECK constraint makes that class of drift impossible: any future
-- attempt to write a non-PBKDF2 hash (bcrypt, argon2, plaintext, etc.) will fail the INSERT/UPDATE.
--
-- Allowed values:
--   * NULL or '' — for in-progress invites where the user hasn't set a password yet
--   * Exact format <32 hex chars>:<64 hex chars> — PBKDF2-HMAC-SHA256, salt+digest
--
-- Pre-flight: 0 LIVE rows violate; 1 soft-deleted row (audit_corporate_client, deleted Apr 6 2026)
-- has a malformed all-zeros placeholder hash — we NULL it as part of this migration since
-- the account is already deleted and the hash is meaningless. The constraint additionally
-- exempts soft-deleted rows so any future soft-delete of a legacy account never blocks here.

-- password_hash is NOT NULL in schema; use empty string (constraint allows '').
UPDATE users
SET password_hash = ''
WHERE deleted_at IS NOT NULL
  AND password_hash <> ''
  AND password_hash !~ '^[0-9a-f]{32}:[0-9a-f]{64}$';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'users_password_hash_format_chk'
          AND conrelid = 'users'::regclass
    ) THEN
        ALTER TABLE users
            ADD CONSTRAINT users_password_hash_format_chk
            CHECK (
                deleted_at IS NOT NULL
                OR password_hash IS NULL
                OR password_hash = ''
                OR password_hash ~ '^[0-9a-f]{32}:[0-9a-f]{64}$'
            );
        RAISE NOTICE 'CHECK constraint users_password_hash_format_chk added';
    ELSE
        RAISE NOTICE 'CHECK constraint users_password_hash_format_chk already exists — skipping';
    END IF;
END $$;

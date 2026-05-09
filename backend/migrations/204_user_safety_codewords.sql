-- Migration 204: User Safety Codewords
-- Plan: Gap 2 — Code-Word Triggers in safe_silence_mode
--       Gap K — Mandatory reporting interaction with codeword-triggered events
-- Depends on: 202 (sensitive_bridge_log)
--
-- Combines the original Gap 2 schema with the v1.3 amendment (197a) that adds
-- triggers_mandatory_reporting. Since this is a NEW table with no production data,
-- the column is included from initial creation rather than as a separate ALTER.
--
-- SECURITY: Codewords are SHA-256 hashed with per-user salt. Plaintext is NEVER
-- stored. Comparison must be constant-time (use hmac.compare_digest in Python).

-- pgcrypto extension for digest() if needed by application-side helpers
-- (the actual hashing is done in Python with hashlib + secrets, but the extension
-- is a useful pre-flight to confirm cryptographic primitives are available)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS user_safety_codewords (
  user_id TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
  codeword_hash TEXT NOT NULL,
    -- sha256(lower(strip_punctuation(codeword)) || per_user_salt) hex digest
  codeword_salt TEXT NOT NULL,
    -- 32-char hex from secrets.token_hex(16); generated per-codeword
  codeword_type TEXT NOT NULL CHECK (codeword_type IN ('explicit_word','innocuous_phrase')),
  codeword_label TEXT,
    -- optional clinician-assigned label (e.g., "primary", "backup");
    -- NEVER contains the codeword itself
  triggers_mandatory_reporting BOOLEAN NOT NULL DEFAULT FALSE,
    -- Gap K: when TRUE, codeword match force-invokes mandatory_reporting
    -- evaluation in addition to coach alert. Set per-codeword by clinician
    -- based on what the codeword means in this survivor's safety plan.
  set_by_clinician_id TEXT NOT NULL,
  set_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
  active BOOLEAN NOT NULL DEFAULT TRUE,
  last_triggered_at TIMESTAMP WITH TIME ZONE,
  trigger_count INT NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, codeword_hash)
);

CREATE INDEX IF NOT EXISTS idx_user_safety_codewords_active
  ON user_safety_codewords(user_id) WHERE active;

COMMENT ON TABLE user_safety_codewords IS
  'Per-user safety codewords for safe_silence_mode emergency channel (Gap 2). '
  'Hashed with per-user salt; plaintext never stored. Match upgrades acuity tier '
  'silently without changing Nate''s outward behavior. triggers_mandatory_reporting '
  '(Gap K) determines whether match also force-invokes mandatory_reporting evaluation.';

COMMENT ON COLUMN user_safety_codewords.codeword_label IS
  'Optional clinician label for tracking purposes (e.g., "primary", "backup"). '
  'MUST NOT contain the codeword itself or any text that hints at it.';

COMMENT ON COLUMN user_safety_codewords.codeword_salt IS
  'Per-codeword salt. POLICY: Generated APPLICATION-SIDE only via '
  'secrets.token_hex(16) in the same Python call that hashes the codeword. '
  'Do NOT add a server-side DEFAULT (e.g., gen_random_bytes) — that would route '
  'salt generation through Postgres and complicate the constant-time-compare '
  'guarantee enforced by hmac.compare_digest in the codeword detector.';

COMMENT ON COLUMN user_safety_codewords.codeword_hash IS
  'sha256(lower(strip_punctuation(codeword)) || codeword_salt) hex digest. '
  'POLICY: Comparison in Python MUST use hmac.compare_digest (constant-time). '
  'Plaintext codeword is NEVER stored, NEVER logged, NEVER returned by any API.';

COMMENT ON COLUMN user_safety_codewords.triggers_mandatory_reporting IS
  'Gap K: When TRUE, a match on this codeword fires mandatory_reporting evaluation '
  'in addition to the standard coach alert. The codeword can be designed to mean '
  '"please report this to authorities" without the user having to say so explicitly.';

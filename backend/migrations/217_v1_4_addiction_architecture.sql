-- ============================================================================
-- Migration 217: Sensitive Bridge v1.4 — Addiction architecture + codeword DDL
-- Idempotent: safe to run twice.
-- Canonical identity: users(username) for all new FKs (no device-id FK paths).
-- ============================================================================

-- --- user_safety_codewords: disclosure_type + part-aware columns -------------
ALTER TABLE user_safety_codewords
  ADD COLUMN IF NOT EXISTS disclosure_type TEXT;

UPDATE user_safety_codewords
   SET disclosure_type = codeword_type
 WHERE disclosure_type IS NULL;

ALTER TABLE user_safety_codewords
  ADD COLUMN IF NOT EXISTS part_name VARCHAR(64),
  ADD COLUMN IF NOT EXISTS part_number INTEGER,
  ADD COLUMN IF NOT EXISTS part_category VARCHAR(32),
  ADD COLUMN IF NOT EXISTS addiction_link VARCHAR(32);

ALTER TABLE user_safety_codewords
  ALTER COLUMN disclosure_type SET DEFAULT 'explicit_word';

UPDATE user_safety_codewords
   SET disclosure_type = 'explicit_word'
 WHERE disclosure_type IS NULL;

ALTER TABLE user_safety_codewords
  ALTER COLUMN disclosure_type SET NOT NULL;

ALTER TABLE user_safety_codewords
  DROP CONSTRAINT IF EXISTS codeword_disclosure_type_check;

ALTER TABLE user_safety_codewords
  ADD CONSTRAINT codeword_disclosure_type_check CHECK (
    disclosure_type IN (
      'explicit_word',
      'innocuous_phrase',
      'soft_pause',
      'grounding_request',
      'covert_observation',
      'reengagement_risk',
      'active_harm',
      'imminent_danger',
      'addict_part_speaking',
      'dissociation_indicator',
      'part_conflict',
      'trafficking_history_disclosure',
      'trafficking_active_risk',
      'trafficking_imminent_danger'
    )
  );

CREATE INDEX IF NOT EXISTS idx_codewords_part_name
  ON user_safety_codewords (user_id, part_name)
  WHERE part_name IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_codewords_addiction_link
  ON user_safety_codewords (user_id, addiction_link)
  WHERE addiction_link IS NOT NULL;

-- --- Per-client parts registry ------------------------------------------------
CREATE TABLE IF NOT EXISTS user_parts_registry (
  id SERIAL PRIMARY KEY,
  user_id VARCHAR(64) NOT NULL REFERENCES users(username) ON DELETE RESTRICT,
  part_name VARCHAR(64) NOT NULL,
  part_number INTEGER,
  part_category VARCHAR(32) NOT NULL,
  addiction_link VARCHAR(32),
  description TEXT,
  protected_exile_part_id INTEGER REFERENCES user_parts_registry(id),
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  created_by VARCHAR(64) NOT NULL,
  retired_at TIMESTAMPTZ,
  UNIQUE (user_id, part_name)
);

CREATE INDEX IF NOT EXISTS idx_parts_registry_user
  ON user_parts_registry (user_id) WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_parts_registry_addiction
  ON user_parts_registry (user_id, addiction_link)
  WHERE addiction_link IS NOT NULL;

-- --- Addiction status history (append-only) ----------------------------------
CREATE TABLE IF NOT EXISTS addiction_status_history (
  id SERIAL PRIMARY KEY,
  user_id VARCHAR(64) NOT NULL REFERENCES users(username) ON DELETE RESTRICT,
  addiction_type VARCHAR(32) NOT NULL,
  previous_status VARCHAR(32),
  new_status VARCHAR(32) NOT NULL,
  subtype VARCHAR(32),
  set_by VARCHAR(64) NOT NULL,
  notes TEXT,
  set_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_addiction_history_user
  ON addiction_status_history (user_id, addiction_type);

-- --- Cross-addiction transfer events ----------------------------------------
CREATE TABLE IF NOT EXISTS cross_addiction_transfer_events (
  id SERIAL PRIMARY KEY,
  user_id VARCHAR(64) NOT NULL REFERENCES users(username) ON DELETE RESTRICT,
  from_addiction VARCHAR(32) NOT NULL,
  to_addiction VARCHAR(32) NOT NULL,
  noted_at TIMESTAMPTZ DEFAULT NOW(),
  noted_by VARCHAR(64) NOT NULL,
  clinical_notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_transfer_user
  ON cross_addiction_transfer_events (user_id);

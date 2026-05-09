-- Migration 206: User Polyvictimization Layers
-- Plan: Gap 8 — Polyvictimization Awareness
-- Depends on: 202 (sensitive_bridge_log)
--
-- Trafficking survivors typically carry layered trauma histories. Each layer
-- interacts with others. This table lets clinicians record those layers so TMC
-- can compute cumulative load via two new signals:
--   - polyvictimization_layer_count (normalized)
--   - polyvictim_severity_load (weighted sum, normalized)
--
-- Severity weights (used in Python TMC, documented here for clarity):
--   low = 1, moderate = 2, high = 4, critical = 6

CREATE TABLE IF NOT EXISTS user_polyvictimization_layers (
  id BIGSERIAL PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
  layer_type TEXT NOT NULL CHECK (layer_type IN (
    'childhood_abuse',
    'family_dysfunction',
    'prior_partner_violence',
    'trafficking',
    'post_trafficking_exploitation',
    'legal_system_trauma',
    'medical_trauma',
    'religious_trauma',
    'community_violence'
  )),
  severity TEXT NOT NULL CHECK (severity IN ('low','moderate','high','critical')),
  active BOOLEAN NOT NULL DEFAULT TRUE,
  set_by_clinician_id TEXT NOT NULL,
  set_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
  notes_redacted TEXT
);

CREATE INDEX IF NOT EXISTS idx_polyvictim_user_active
  ON user_polyvictimization_layers(user_id) WHERE active;

COMMENT ON TABLE user_polyvictimization_layers IS
  'Clinician-set layered trauma histories. Used by TMC to compute cumulative load. '
  'Crystal recall cross-references active layers to prefer crystals tagged with '
  'overlapping layer_relevance markers. PGSD ingests layer interactions; '
  'cycle_detection_engine spans across layers.';

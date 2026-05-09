-- Migration 203: User Linguistic Baseline + Coercive Voice Profiles
-- Plan: Gap 1 — Introjection / Voice-Shift Mirror
-- Depends on: 202 (sensitive_bridge_log)
--
-- Coordination note: user_linguistic_baseline is shared with the phase-coherence-audit
-- UserBaselineService gap. There is ONE baseline service. Do not create a second table
-- for the same purpose elsewhere.

-- ============================================================
-- user_linguistic_baseline — per-user baseline used by introjection_voice_mirror
-- ============================================================

CREATE TABLE IF NOT EXISTS user_linguistic_baseline (
  user_id TEXT PRIMARY KEY REFERENCES users(username) ON DELETE CASCADE,
  baseline_vector JSONB NOT NULL,
    -- expected keys: avg_msg_length, pos_ratio, pronoun_distribution,
    -- register_centroid, sentiment_baseline, vocabulary_complexity
  sample_count INT NOT NULL DEFAULT 0,
  last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  baseline_locked BOOLEAN NOT NULL DEFAULT FALSE
    -- clinician locks after N>=50 samples judged stable
);

COMMENT ON TABLE user_linguistic_baseline IS
  'Per-user linguistic baseline vector. Used by introjection_voice_mirror to detect '
  'fawn-response and trafficker-voice introjection via cosine distance from baseline. '
  'Coordinates with phase-coherence UserBaselineService (single shared table).';

-- ============================================================
-- coercive_voice_profiles — global registry of known coercive linguistic profiles
-- ============================================================

CREATE TABLE IF NOT EXISTS coercive_voice_profiles (
  profile_id TEXT PRIMARY KEY,
    -- canonical values: 'trafficker_classic', 'fawn_compliance',
    -- 'transactional_minimization', 'self_blame_loop'
  marker_lexicon JSONB NOT NULL,
  syntactic_signatures JSONB NOT NULL,
  literature_refs TEXT[] NOT NULL DEFAULT '{}',
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE coercive_voice_profiles IS
  'Registry of known coercive linguistic profiles for introjection detection. '
  'profile_id values are canonical and referenced by introjection_voice_mirror.';

-- Seed the four canonical profiles with empty lexicons; clinician fills via portal/PR.
-- Empty arrays are intentional — clinician authoring is a separate review-gated step.
INSERT INTO coercive_voice_profiles (profile_id, marker_lexicon, syntactic_signatures, literature_refs)
VALUES
  ('trafficker_classic',
   '{"markers": [], "weight_default": 0.0}'::jsonb,
   '{"signatures": []}'::jsonb,
   ARRAY['Hopper 2017', 'Polaris training materials', 'Zimmerman et al.']),
  ('fawn_compliance',
   '{"markers": [], "weight_default": 0.0}'::jsonb,
   '{"signatures": []}'::jsonb,
   ARRAY['Walker 2013 (CPTSD: From Surviving to Thriving)']),
  ('transactional_minimization',
   '{"markers": [], "weight_default": 0.0}'::jsonb,
   '{"signatures": []}'::jsonb,
   ARRAY['Herman 1992 (Trauma and Recovery)']),
  ('self_blame_loop',
   '{"markers": [], "weight_default": 0.0}'::jsonb,
   '{"signatures": []}'::jsonb,
   ARRAY['Najavits 2002 (Seeking Safety)'])
ON CONFLICT (profile_id) DO NOTHING;

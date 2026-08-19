-- Sovereign Studio S1 — shows, persona versions, coach models.
-- Additive only. QUANTUM-CRYSTAL-ARCH

CREATE TABLE IF NOT EXISTS studio_shows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coach_id VARCHAR NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    vertical TEXT NOT NULL,
    host_number TEXT,
    host_verified BOOLEAN NOT NULL DEFAULT FALSE,
    gv_forwarding BOOLEAN NOT NULL DEFAULT FALSE,
    did_e164 TEXT,
    persona_style_layer JSONB NOT NULL DEFAULT '{}'::jsonb,
    tier TEXT NOT NULL DEFAULT 'tier1',
    live_unlocked BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT studio_shows_vertical_chk CHECK (
        vertical IN (
            'life_coaching',
            'grief',
            'relationships_intimacy',
            'trauma_modalities',
            'neuroscience_education'
        )
    ),
    CONSTRAINT studio_shows_tier_chk CHECK (tier IN ('tier1', 'tier2'))
);

CREATE INDEX IF NOT EXISTS idx_studio_shows_coach
    ON studio_shows (coach_id, created_at DESC);

CREATE TABLE IF NOT EXISTS studio_persona_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    layer TEXT NOT NULL,
    vertical TEXT,
    version TEXT NOT NULL,
    document JSONB NOT NULL,
    writable_by TEXT NOT NULL DEFAULT 'platform_admin',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT studio_persona_layer_chk CHECK (layer IN ('guardrail', 'vertical')),
    CONSTRAINT studio_persona_writable_chk CHECK (writable_by = 'platform_admin')
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_studio_persona_versions_uniq
    ON studio_persona_versions (layer, COALESCE(vertical, ''), version);

CREATE TABLE IF NOT EXISTS studio_coach_models (
    coach_id VARCHAR PRIMARY KEY,
    pacing JSONB NOT NULL DEFAULT '{}'::jsonb,
    toss_cues JSONB NOT NULL DEFAULT '[]'::jsonb,
    turn_taking_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    clone_voice_id TEXT,
    clone_consent BOOLEAN NOT NULL DEFAULT FALSE,
    clone_consent_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO studio_persona_versions (layer, vertical, version, document, writable_by)
VALUES (
    'guardrail',
    NULL,
    '1.0',
    '{
      "role": "AI co-host and knowledge companion",
      "prohibited": ["clinical", "therapy", "diagnose", "treatment", "prescribe", "assess your case"],
      "rules": [
        "Educational co-host only. Never market as clinician or advisor.",
        "Do not diagnose, treat, or prescribe.",
        "Redirect crisis language to the screener private-support path."
      ]
    }'::jsonb,
    'platform_admin'
)
ON CONFLICT DO NOTHING;

INSERT INTO studio_persona_versions (layer, vertical, version, document, writable_by)
VALUES
(
    'vertical', 'life_coaching', '1.0',
    '{"vertical":"life_coaching","frame":"goals, habits, accountability","avoid":["clinical assessment"]}'::jsonb,
    'platform_admin'
),
(
    'vertical', 'grief', '1.0',
    '{"vertical":"grief","frame":"presence, naming loss, pacing","avoid":["stages as diagnosis"]}'::jsonb,
    'platform_admin'
),
(
    'vertical', 'relationships_intimacy', '1.0',
    '{"vertical":"relationships_intimacy","frame":"patterns, bids, repair language","avoid":["couples therapy claims"]}'::jsonb,
    'platform_admin'
),
(
    'vertical', 'trauma_modalities', '1.0',
    '{"vertical":"trauma_modalities","frame":"education about modalities, not treatment","avoid":["treat your trauma"]}'::jsonb,
    'platform_admin'
),
(
    'vertical', 'neuroscience_education', '1.0',
    '{"vertical":"neuroscience_education","frame":"accessible brain science for coaching","avoid":["neuroclinical advice"]}'::jsonb,
    'platform_admin'
)
ON CONFLICT DO NOTHING;

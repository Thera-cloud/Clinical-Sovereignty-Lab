-- Migration 179: UCD Phase 1 — Foundation tables for Unified Creative Director
-- Covers: narrative_state_objects, nso_history, ucd_creative_directives,
-- sse_delivery_generation_log extensions, prerequisite signal tables,
-- heritage_correlation_index, voice_session_features_summary,
-- mask_detection_state, deployment_context, intensity_ledger,
-- character_lora_models, tmc_training_data

-- ============================================================
-- 1. Narrative State Objects (shared NSO)
-- ============================================================
CREATE TABLE IF NOT EXISTS narrative_state_objects (
    nso_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             TEXT NOT NULL UNIQUE,
    act_position        TEXT NOT NULL DEFAULT 'act_1',
    arc_label           TEXT,
    protagonist_state   JSONB DEFAULT '{}'::jsonb,
    active_themes       JSONB DEFAULT '[]'::jsonb,
    unresolved_threads  JSONB DEFAULT '[]'::jsonb,
    resolved_threads    JSONB DEFAULT '[]'::jsonb,
    last_generation_id  UUID,
    generation_sequence INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_nso_user ON narrative_state_objects(user_id);

-- ============================================================
-- 2. NSO History (corruption recovery — last N snapshots per user)
-- ============================================================
CREATE TABLE IF NOT EXISTS nso_history (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             TEXT NOT NULL,
    nso_snapshot        JSONB NOT NULL,
    generation_id       UUID,
    reason              TEXT DEFAULT 'pre_mutation',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_nso_history_user ON nso_history(user_id, created_at DESC);

-- ============================================================
-- 3. UCD Creative Directives (Phase 4 logging, schema created early)
-- ============================================================
CREATE TABLE IF NOT EXISTS ucd_creative_directives (
    directive_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             TEXT NOT NULL,
    moment_class        TEXT NOT NULL,
    selected_modality   TEXT NOT NULL,
    delivery_window     JSONB DEFAULT '{}'::jsonb,
    lora_model_ref      TEXT,
    nso_snapshot        JSONB,
    directive_payload   JSONB NOT NULL DEFAULT '{}'::jsonb,
    pipeline_target     TEXT,
    status              TEXT DEFAULT 'pending',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    executed_at         TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_ucd_directives_user ON ucd_creative_directives(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ucd_directives_status ON ucd_creative_directives(status);

-- ============================================================
-- 4. Extend sse_delivery_generation_log with UCD columns
-- ============================================================
ALTER TABLE sse_delivery_generation_log ADD COLUMN IF NOT EXISTS directive_id UUID;
ALTER TABLE sse_delivery_generation_log ADD COLUMN IF NOT EXISTS moment_class TEXT;
ALTER TABLE sse_delivery_generation_log ADD COLUMN IF NOT EXISTS nso_snapshot JSONB;
ALTER TABLE sse_delivery_generation_log ADD COLUMN IF NOT EXISTS creative_directive JSONB;
ALTER TABLE sse_delivery_generation_log ADD COLUMN IF NOT EXISTS engagement_action TEXT;
ALTER TABLE sse_delivery_generation_log ADD COLUMN IF NOT EXISTS user_response_crystal_ids UUID[] DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_gen_log_directive ON sse_delivery_generation_log(directive_id) WHERE directive_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_gen_log_moment ON sse_delivery_generation_log(moment_class) WHERE moment_class IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_gen_log_engagement ON sse_delivery_generation_log(engagement_action) WHERE engagement_action IS NOT NULL;

-- ============================================================
-- 5. Deployment context on sse_identity_forge
-- ============================================================
ALTER TABLE sse_identity_forge ADD COLUMN IF NOT EXISTS deployment_context TEXT DEFAULT 'private';
ALTER TABLE sse_identity_forge ADD COLUMN IF NOT EXISTS mask_detection_state TEXT DEFAULT 'UNMASKED';

-- ============================================================
-- 6. Prerequisite signal tables
-- ============================================================

-- Parts Registry
CREATE TABLE IF NOT EXISTS sse_parts_registry (
    part_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             TEXT NOT NULL,
    part_name           TEXT NOT NULL,
    part_role           TEXT,
    emotional_valence   FLOAT DEFAULT 0.0,
    activation_level    FLOAT DEFAULT 0.0,
    associated_crystals UUID[] DEFAULT '{}',
    metadata            JSONB DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_parts_user ON sse_parts_registry(user_id);

-- Workbook progress
CREATE TABLE IF NOT EXISTS sse_workbook_progress (
    progress_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             TEXT NOT NULL,
    workbook_id         TEXT NOT NULL,
    chapter_index       INTEGER DEFAULT 0,
    section_index       INTEGER DEFAULT 0,
    completion_pct      FLOAT DEFAULT 0.0,
    reflections         JSONB DEFAULT '[]'::jsonb,
    last_active_at      TIMESTAMPTZ DEFAULT NOW(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, workbook_id)
);
CREATE INDEX IF NOT EXISTS idx_workbook_progress_user ON sse_workbook_progress(user_id);

-- Biome state
CREATE TABLE IF NOT EXISTS sse_biome_state (
    biome_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             TEXT NOT NULL UNIQUE,
    current_biome       TEXT NOT NULL DEFAULT 'forest',
    biome_weather       TEXT DEFAULT 'clear',
    biome_season        TEXT DEFAULT 'spring',
    emotional_terrain   JSONB DEFAULT '{}'::jsonb,
    transition_history  JSONB DEFAULT '[]'::jsonb,
    last_transition_at  TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_biome_state_user ON sse_biome_state(user_id);

-- ============================================================
-- 7. Heritage correlation index (materialized view)
-- ============================================================
CREATE MATERIALIZED VIEW IF NOT EXISTS heritage_correlation_index AS
SELECT
    tp.pattern_id,
    tp.pattern_name,
    c.domain AS crystal_domain,
    c.user_id AS crystal_user_id,
    c.confidence AS crystal_confidence,
    tp.confidence AS pattern_confidence,
    tp.effect_size,
    COALESCE(tp.confidence, 0) * COALESCE(c.confidence, 0) AS correlation_strength,
    tp.created_at AS pattern_created_at,
    c.created_at AS crystal_created_at
FROM transgenerational_patterns tp
CROSS JOIN LATERAL (
    SELECT id, domain, user_id, confidence, created_at
    FROM nate_intelligence_crystals
    WHERE domain IN ('clinical', 'coaching', 'culture')
      AND confidence >= 0.55
      AND superseded_by IS NULL
      AND scope != 'archived'
    ORDER BY confidence DESC
    LIMIT 100
) c
WHERE tp.confidence >= 0.3
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_heritage_corr_pk
    ON heritage_correlation_index(pattern_id, crystal_domain, COALESCE(crystal_user_id::text, ''));

-- ============================================================
-- 8. Voice session features summary (view)
-- ============================================================
CREATE OR REPLACE VIEW voice_session_features_summary AS
SELECT
    user_uuid,
    COUNT(*) AS session_count,
    AVG((payload->>'pitch_mean')::float) FILTER (WHERE payload->>'pitch_mean' IS NOT NULL) AS avg_pitch_mean,
    AVG((payload->>'energy')::float) FILTER (WHERE payload->>'energy' IS NOT NULL) AS avg_energy,
    AVG((payload->>'speech_rate')::float) FILTER (WHERE payload->>'speech_rate' IS NOT NULL) AS avg_speech_rate,
    AVG((payload->>'pause_ratio')::float) FILTER (WHERE payload->>'pause_ratio' IS NOT NULL) AS avg_pause_ratio,
    MAX(created_at) AS last_session_at,
    MIN(created_at) AS first_session_at
FROM voice_session_biometrics
WHERE user_uuid IS NOT NULL
GROUP BY user_uuid;

-- ============================================================
-- 9. Intensity ledger (Safety S1)
-- ============================================================
CREATE TABLE IF NOT EXISTS intensity_ledger (
    ledger_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             TEXT NOT NULL,
    moment_class        TEXT NOT NULL,
    intensity_score     FLOAT NOT NULL DEFAULT 0.0,
    generation_id       UUID,
    source_directive_id UUID,
    clinician_override  BOOLEAN DEFAULT false,
    override_reason     TEXT,
    clinician_override_limit FLOAT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_intensity_user_class ON intensity_ledger(user_id, moment_class, created_at DESC);

-- ============================================================
-- 10. Character LoRA models registry (Phase 3)
-- ============================================================
CREATE TABLE IF NOT EXISTS character_lora_models (
    model_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             TEXT NOT NULL,
    project_id          TEXT,
    replicate_model_ref TEXT NOT NULL,
    r2_adapter_key      TEXT,
    training_images     INTEGER DEFAULT 0,
    trigger_word        TEXT,
    base_model          TEXT,
    status              TEXT DEFAULT 'ready',
    metadata            JSONB DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_lora_models_user ON character_lora_models(user_id);
CREATE INDEX IF NOT EXISTS idx_lora_models_project ON character_lora_models(project_id) WHERE project_id IS NOT NULL;

-- ============================================================
-- 11. TMC training data (Phase 5)
-- ============================================================
CREATE TABLE IF NOT EXISTS tmc_training_data (
    sample_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             TEXT NOT NULL,
    input_signals       JSONB NOT NULL,
    classified_moment   TEXT NOT NULL,
    actual_engagement   TEXT,
    generation_id       UUID,
    crystal_response_ids UUID[] DEFAULT '{}',
    model_version       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tmc_training_user ON tmc_training_data(user_id, created_at DESC);

-- ============================================================
-- 12. Add generation_id FK column to nate_intelligence_crystals (Phase 5 linkage)
-- ============================================================
ALTER TABLE nate_intelligence_crystals ADD COLUMN IF NOT EXISTS generation_id UUID;
CREATE INDEX IF NOT EXISTS idx_crystals_generation_id ON nate_intelligence_crystals(generation_id) WHERE generation_id IS NOT NULL;

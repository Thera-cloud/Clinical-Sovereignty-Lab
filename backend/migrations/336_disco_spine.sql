-- 336_disco_spine.sql
-- GEO discoverability spine. Additive only. Does not recreate 328 tables.
-- Flags stay OFF until T1 gate. Public /coaches/* unpublished until DISCO_RENDER.

BEGIN;

-- ── Widen campaign_engagements for T3.3 ai_search ──
ALTER TABLE campaign_engagements ADD COLUMN IF NOT EXISTS channel TEXT;
ALTER TABLE campaign_engagements ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE campaign_engagements ADD COLUMN IF NOT EXISTS prospect_email TEXT;

CREATE INDEX IF NOT EXISTS idx_campaign_engagements_channel
    ON campaign_engagements (channel) WHERE channel IS NOT NULL;

-- ── Canonical coach identity (T1.1) — coach_id = users.username ──
CREATE TABLE IF NOT EXISTS canonical_identity (
    coach_id            VARCHAR PRIMARY KEY,
    display_name        TEXT NOT NULL,
    credential_string   TEXT NOT NULL DEFAULT '',
    service_mode        TEXT NOT NULL DEFAULT 'virtual',
    area_served         JSONB NOT NULL DEFAULT '[]'::jsonb,
    canonical_phrases   TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    languages           TEXT[] NOT NULL DEFAULT ARRAY['en']::TEXT[],
    profile_status      TEXT NOT NULL DEFAULT 'draft'
                        CHECK (profile_status IN ('draft', 'active', 'paused', 'departed')),
    same_as             JSONB NOT NULL DEFAULT '[]'::jsonb,
    slug                TEXT NOT NULL,
    bio                 TEXT NOT NULL DEFAULT '',
    version             INTEGER NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_canonical_identity_slug
    ON canonical_identity (slug);

-- ── Vocabulary taxonomy (T1.2) ──
CREATE TABLE IF NOT EXISTS vocabulary_taxonomy (
    id              BIGSERIAL PRIMARY KEY,
    concept         TEXT NOT NULL,
    language        TEXT NOT NULL,
    register        TEXT NOT NULL CHECK (register IN ('clinical', 'coaching')),
    terms           TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    query_phrases   TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    acronyms        TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    entity_uri      TEXT,
    seed_complete   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_vocabulary_taxonomy_row
    ON vocabulary_taxonomy (concept, language, register);

-- ── Discovery pages ──
CREATE TABLE IF NOT EXISTS discovery_pages (
    id                  BIGSERIAL PRIMARY KEY,
    page_type           TEXT NOT NULL,
    slug                TEXT NOT NULL,
    entity_ref          TEXT,
    status              TEXT NOT NULL DEFAULT 'draft',
    last_rendered_at    TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_discovery_pages_type_slug
    ON discovery_pages (page_type, slug);

-- ── Visibility probes (T3.1) ──
CREATE TABLE IF NOT EXISTS visibility_probes (
    id              BIGSERIAL PRIMARY KEY,
    class_id        TEXT NOT NULL,
    prompt          TEXT NOT NULL,
    last_run_at     TIMESTAMPTZ,
    last_engine     TEXT,
    last_named      BOOLEAN,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_visibility_probes_prompt
    ON visibility_probes (prompt);

-- ── Recruiting + trends ──
CREATE TABLE IF NOT EXISTS recruiting_targets (
    id              BIGSERIAL PRIMARY KEY,
    specialty       TEXT NOT NULL,
    geo             TEXT NOT NULL,
    language        TEXT NOT NULL DEFAULT 'en',
    monthly_searches INTEGER NOT NULL DEFAULT 0,
    coach_count     INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS trending_topics (
    id              BIGSERIAL PRIMARY KEY,
    topic           TEXT NOT NULL,
    language        TEXT NOT NULL DEFAULT 'en',
    score           NUMERIC NOT NULL DEFAULT 0,
    ethics_flag     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Coach-flagged topics (content_topics contract) ──
CREATE TABLE IF NOT EXISTS disco_content_topics (
    id              BIGSERIAL PRIMARY KEY,
    coach_id        VARCHAR NOT NULL,
    topic           TEXT NOT NULL,
    flagged_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Approval queue (#39) — A3 never auto-publishes ──
CREATE TABLE IF NOT EXISTS disco_approval_queue (
    id              BIGSERIAL PRIMARY KEY,
    kind            TEXT NOT NULL,
    risk            TEXT NOT NULL DEFAULT 'judgment',
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    auto_approved   BOOLEAN NOT NULL DEFAULT FALSE,
    publish_requires_human BOOLEAN NOT NULL DEFAULT FALSE,
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Claims + corrections (T3.2) ──
CREATE TABLE IF NOT EXISTS disco_claims_log (
    id              BIGSERIAL PRIMARY KEY,
    surface         TEXT NOT NULL,
    claim_text      TEXT NOT NULL,
    blocked         BOOLEAN NOT NULL DEFAULT FALSE,
    reasons         TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Listing / GBP tracker (T1.14–15, DAC31) ──
CREATE TABLE IF NOT EXISTS disco_listing_status (
    coach_id        VARCHAR NOT NULL,
    platform        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'packet_ready',
    human_step      TEXT,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (coach_id, platform)
);

-- ── Funnel events (T3.4) ──
CREATE TABLE IF NOT EXISTS disco_funnel_events (
    id              BIGSERIAL PRIMARY KEY,
    coach_id        VARCHAR,
    step            TEXT NOT NULL,
    channel         TEXT,
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Autonomy config row (T4.11) ──
CREATE TABLE IF NOT EXISTS disco_autonomy_config (
    id              INTEGER PRIMARY KEY DEFAULT 1,
    version         TEXT NOT NULL,
    config          JSONB NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO disco_autonomy_config (id, version, config)
VALUES (1, '1.1', '{
  "adapt_freeze": false,
  "a3_publish_requires_human": true,
  "a3_auto_approve_on_timeout": false
}'::jsonb)
ON CONFLICT (id) DO NOTHING;

-- ── T1.2 EN seed: 10 concepts × clinical/coaching ──
INSERT INTO vocabulary_taxonomy (concept, language, register, terms, query_phrases, acronyms, seed_complete)
VALUES
('Family Systems', 'en', 'clinical',
 ARRAY['Family Systems Therapy','Structural Family Therapy'],
 ARRAY['family communication issues','how to fix broken family dynamics','family boundary support'],
 ARRAY['FST'], TRUE),
('Family Systems', 'en', 'coaching',
 ARRAY['Family Systems & Dynamics Coaching'],
 ARRAY['family communication issues','how to fix broken family dynamics','family boundary support'],
 ARRAY['FST'], TRUE),
('Trauma & PTSD', 'en', 'clinical',
 ARRAY['Trauma-Informed Psychotherapy','Post-Traumatic Stress Treatment'],
 ARRAY['trauma-informed coach near me','help processing past trauma','somatic trauma support'],
 ARRAY['PTSD','C-PTSD'], TRUE),
('Trauma & PTSD', 'en', 'coaching',
 ARRAY['Trauma-Informed Integration Coaching'],
 ARRAY['trauma-informed coach near me','help processing past trauma','somatic trauma support'],
 ARRAY['PTSD','C-PTSD'], TRUE),
('Perinatal & Postpartum', 'en', 'clinical',
 ARRAY['Perinatal Mental Health','Postpartum Depression/Anxiety Treatment'],
 ARRAY['postpartum rage help','postpartum anxiety therapist online','new mom burnout'],
 ARRAY['PPD','PPA'], TRUE),
('Perinatal & Postpartum', 'en', 'coaching',
 ARRAY['Postpartum & Perinatal Transition Coaching'],
 ARRAY['postpartum rage help','postpartum anxiety therapist online','new mom burnout'],
 ARRAY['PPD','PPA'], TRUE),
('Addiction & Recovery', 'en', 'clinical',
 ARRAY['Substance Use Disorder Counseling','Harm Reduction Therapy'],
 ARRAY['sobriety coach near me','addiction recovery support online','accountability in recovery'],
 ARRAY['SUD','MAT'], TRUE),
('Addiction & Recovery', 'en', 'coaching',
 ARRAY['Recovery & Sobriety Support Coaching'],
 ARRAY['sobriety coach near me','addiction recovery support online','accountability in recovery'],
 ARRAY['SUD','MAT'], TRUE),
('Burnout & Executive', 'en', 'clinical',
 ARRAY['Occupational Stress Syndrome','Clinical Exhaustion'],
 ARRAY['executive burnout recovery','overwhelmed manager support','career boundary coaching'],
 ARRAY[]::TEXT[], TRUE),
('Burnout & Executive', 'en', 'coaching',
 ARRAY['Executive Resilience & Burnout Coaching'],
 ARRAY['executive burnout recovery','overwhelmed manager support','career boundary coaching'],
 ARRAY[]::TEXT[], TRUE),
('Grief & Loss', 'en', 'clinical',
 ARRAY['Complicated Grief Therapy','Bereavement Counseling'],
 ARRAY['grief support after sudden loss','how to move through grief','bereavement support coach'],
 ARRAY[]::TEXT[], TRUE),
('Grief & Loss', 'en', 'coaching',
 ARRAY['Grief Processing & Life Transition Coaching'],
 ARRAY['grief support after sudden loss','how to move through grief','bereavement support coach'],
 ARRAY[]::TEXT[], TRUE),
('Adolescent & Teen', 'en', 'clinical',
 ARRAY['Adolescent Behavioral Therapy','Pediatric Mental Health'],
 ARRAY['coach for anxious teenager','teen boundary support','adolescent life coach'],
 ARRAY[]::TEXT[], TRUE),
('Adolescent & Teen', 'en', 'coaching',
 ARRAY['Teen Transition & Life Skills Coaching'],
 ARRAY['coach for anxious teenager','teen boundary support','adolescent life coach'],
 ARRAY[]::TEXT[], TRUE),
('Couples & Relationship', 'en', 'clinical',
 ARRAY['Relational Psychotherapy','Marital Therapy'],
 ARRAY['couples communication coach','intimacy barriers help','relationship conflict help'],
 ARRAY['EFT','Gottman'], TRUE),
('Couples & Relationship', 'en', 'coaching',
 ARRAY['Relationship & Communication Coaching'],
 ARRAY['couples communication coach','intimacy barriers help','relationship conflict help'],
 ARRAY['EFT','Gottman'], TRUE),
('ADHD & Neurodivergence', 'en', 'clinical',
 ARRAY['Adult ADHD Diagnostic & Therapeutic Management'],
 ARRAY['ADHD coach for adults','executive dysfunction help','neurodivergent burnout support'],
 ARRAY['ADHD'], TRUE),
('ADHD & Neurodivergence', 'en', 'coaching',
 ARRAY['Neurodivergent Functioning & ADHD Coaching'],
 ARRAY['ADHD coach for adults','executive dysfunction help','neurodivergent burnout support'],
 ARRAY['ADHD'], TRUE),
('Somatic Integration', 'en', 'clinical',
 ARRAY['Somatic Experiencing','Sensorimotor Psychotherapy'],
 ARRAY['nervous system regulation coach','somatic exercise for anxiety','somatic practitioner'],
 ARRAY['SE'], TRUE),
('Somatic Integration', 'en', 'coaching',
 ARRAY['Somatic Awareness & Body-Based Alignment'],
 ARRAY['nervous system regulation coach','somatic exercise for anxiety','somatic practitioner'],
 ARRAY['SE'], TRUE)
ON CONFLICT (concept, language, register) DO NOTHING;

-- DE/FR coaching seed-only (C6 — incomplete until native query phrasing)
INSERT INTO vocabulary_taxonomy (concept, language, register, terms, query_phrases, acronyms, seed_complete)
VALUES
('Family Systems', 'de', 'coaching', ARRAY['Familiendynamik Coaching'], ARRAY[]::TEXT[], ARRAY[]::TEXT[], FALSE),
('Family Systems', 'fr', 'coaching', ARRAY['Coaching de dynamique familiale'], ARRAY[]::TEXT[], ARRAY[]::TEXT[], FALSE),
('Trauma & PTSD', 'de', 'coaching', ARRAY['Traumainformiertes Coaching'], ARRAY[]::TEXT[], ARRAY[]::TEXT[], FALSE),
('Trauma & PTSD', 'fr', 'coaching', ARRAY['Coaching informé sur le traumatisme'], ARRAY[]::TEXT[], ARRAY[]::TEXT[], FALSE),
('Perinatal & Postpartum', 'de', 'coaching', ARRAY['Postpartale Unterstützung'], ARRAY[]::TEXT[], ARRAY[]::TEXT[], FALSE),
('Perinatal & Postpartum', 'fr', 'coaching', ARRAY['Support dépression postpartum'], ARRAY[]::TEXT[], ARRAY[]::TEXT[], FALSE),
('Addiction & Recovery', 'de', 'coaching', ARRAY['Suchtbewältigung Coaching'], ARRAY[]::TEXT[], ARRAY[]::TEXT[], FALSE),
('Addiction & Recovery', 'fr', 'coaching', ARRAY['Accompagnement en addiction'], ARRAY[]::TEXT[], ARRAY[]::TEXT[], FALSE),
('Burnout & Executive', 'de', 'coaching', ARRAY['Burnout-Prävention Coaching'], ARRAY[]::TEXT[], ARRAY[]::TEXT[], FALSE),
('Burnout & Executive', 'fr', 'coaching', ARRAY['Coaching de prévention du burnout'], ARRAY[]::TEXT[], ARRAY[]::TEXT[], FALSE),
('Grief & Loss', 'de', 'coaching', ARRAY['Trauerbegleitung'], ARRAY[]::TEXT[], ARRAY[]::TEXT[], FALSE),
('Grief & Loss', 'fr', 'coaching', ARRAY['Accompagnement du deuil'], ARRAY[]::TEXT[], ARRAY[]::TEXT[], FALSE),
('Adolescent & Teen', 'de', 'coaching', ARRAY['Jugend- & Teenager-Coaching'], ARRAY[]::TEXT[], ARRAY[]::TEXT[], FALSE),
('Adolescent & Teen', 'fr', 'coaching', ARRAY['Coaching pour adolescents'], ARRAY[]::TEXT[], ARRAY[]::TEXT[], FALSE),
('Couples & Relationship', 'de', 'coaching', ARRAY['Beziehungs- & Paarcoaching'], ARRAY[]::TEXT[], ARRAY[]::TEXT[], FALSE),
('Couples & Relationship', 'fr', 'coaching', ARRAY['Coaching de couple et relationnel'], ARRAY[]::TEXT[], ARRAY[]::TEXT[], FALSE),
('ADHD & Neurodivergence', 'de', 'coaching', ARRAY['ADHS Coaching für Erwachsene'], ARRAY[]::TEXT[], ARRAY[]::TEXT[], FALSE),
('ADHD & Neurodivergence', 'fr', 'coaching', ARRAY['Coaching TDAH adultes'], ARRAY[]::TEXT[], ARRAY[]::TEXT[], FALSE),
('Somatic Integration', 'de', 'coaching', ARRAY['Somatische Nervensystem-Regulation'], ARRAY[]::TEXT[], ARRAY[]::TEXT[], FALSE),
('Somatic Integration', 'fr', 'coaching', ARRAY['Régulation somatique du système nerveux'], ARRAY[]::TEXT[], ARRAY[]::TEXT[], FALSE)
ON CONFLICT (concept, language, register) DO NOTHING;

-- T3.1 probe set (32)
INSERT INTO visibility_probes (class_id, prompt) VALUES
('G1_HEAD_LOCAL', 'family coach near Detroit MI'),
('G1_HEAD_LOCAL', 'trauma-informed therapist near Austin TX'),
('G1_HEAD_LOCAL', 'postpartum anxiety coach in California'),
('G1_HEAD_LOCAL', 'grief counselor near Chicago IL'),
('G2_LONGTAIL', 'somatic trauma integration coach in Michigan accepting virtual clients'),
('G2_LONGTAIL', 'executive burnout coach in Germany speaking English'),
('G2_LONGTAIL', 'perinatal depression therapist in France offering virtual support'),
('G2_LONGTAIL', 'ADHD coach for adults specializing in executive dysfunction in New York'),
('G3_VIRTUAL', 'best virtual family systems coaches online'),
('G3_VIRTUAL', 'licensed online therapist for postpartum rage'),
('G3_VIRTUAL', 'remote sobriety and addiction recovery coach'),
('G3_VIRTUAL', 'neurodivergent-affirming relationship coach online'),
('G4_PRODUCT', 'AI therapy app that works alongside real human therapists'),
('G4_PRODUCT', 'mental health app with an AI companion that remembers my history'),
('G4_PRODUCT', 'AI assistant paired with licensed coaches for between sessions'),
('G4_PRODUCT', 'is there an AI companion that connects you to family coaches'),
('G5_AFFORD', 'affordable mental health support plan for a family'),
('G5_AFFORD', 'therapy alternative when I can''t afford weekly sessions'),
('G5_AFFORD', 'family mental health plan under $150 a month'),
('G5_AFFORD', 'low-cost postpartum coaching options'),
('G6_BRAND', 'is Sovereign Sanctuary legitimate'),
('G6_BRAND', 'Sovereign Sanctuary reviews and pricing'),
('G6_BRAND', 'who is Nathaniel Nevedal'),
('G6_BRAND', 'how does Sovereign Sanctuary verify its coaches'),
('G7_UPSTREAM', 'why do I feel numb after having a baby'),
('G7_UPSTREAM', 'how do I know if I need therapy or a coach'),
('G7_UPSTREAM', 'postpartum rage — is that normal'),
('G7_UPSTREAM', 'why am I burned out but can''t rest'),
('G8_RECRUIT', 'platforms for therapists to see clients online'),
('G8_RECRUIT', 'how do coaches get clients'),
('G8_RECRUIT', 'telehealth platform for licensed therapists'),
('G8_RECRUIT', 'best platform for certified coaches to build a practice')
ON CONFLICT (prompt) DO NOTHING;

COMMIT;

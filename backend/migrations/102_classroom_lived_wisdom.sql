-- Migration 102: Classroom Lived Wisdom — PostgreSQL-backed session analyses
-- Ensures client–coach session wisdom is not lost; supports CEE/PMB and liminal intelligence.
-- See .cursor/plans/lived_wisdom_persistence_addendum_6996a4c1.plan.md

CREATE TABLE IF NOT EXISTS classroom_session_analyses (
    session_id              VARCHAR(64) PRIMARY KEY,
    coach_id                VARCHAR(128) NOT NULL,
    client_id               VARCHAR(128) NOT NULL,
    client_name             VARCHAR(256) DEFAULT '',
    family_id               VARCHAR(128) DEFAULT '',
    status                  VARCHAR(64) DEFAULT 'pending_dojo_selection'
        CHECK (status IN ('pending_dojo_selection', 'assessing', 'completed')),
    analyzed_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    transcript_hash         VARCHAR(64) DEFAULT '',
    metrics                 JSONB DEFAULT '{}'::jsonb,
    cee_signals             JSONB DEFAULT '[]'::jsonb,
    selected_dojos          JSONB DEFAULT '[]'::jsonb,
    assessments             JSONB DEFAULT '{}'::jsonb,
    therapeutic_presence_score DOUBLE PRECISION DEFAULT 0,
    final_assessment_doc_id VARCHAR(256) DEFAULT '',
    completed_at            TIMESTAMPTZ,
    payload                 JSONB DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_classroom_analyses_coach ON classroom_session_analyses(coach_id);
CREATE INDEX IF NOT EXISTS idx_classroom_analyses_client ON classroom_session_analyses(client_id);
CREATE INDEX IF NOT EXISTS idx_classroom_analyses_status ON classroom_session_analyses(status);
CREATE INDEX IF NOT EXISTS idx_classroom_analyses_analyzed_at ON classroom_session_analyses(analyzed_at DESC);

COMMENT ON TABLE classroom_session_analyses IS 'Lived wisdom from coach–client sessions; canonical store for Classroom + CEE/PMB/liminal intelligence';

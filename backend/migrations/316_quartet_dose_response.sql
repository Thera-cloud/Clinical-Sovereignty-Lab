-- Quartet dose-response scoring queue (D.14b capability-track extension).
--
-- Purpose: score the safety quartet (AQ-1, AQ-2, AQ-G07, AQ-G08) under two
-- conditions — before_no_affinity vs after_affinity_fix — side by side, with a
-- move-level checklist, WITHOUT touching six_quotient_human_gold (which only
-- holds one row per scenario_id and cannot carry two generations at once).
--
-- Read-only against generation data: "after" rows are snapshotted at seed time
-- from six_quotient_human_gold.nate_response_live (never written back there).
-- "before" rows are ingested from a recovered transcript file (the DB row was
-- overwritten by a later regeneration) — see
-- backend/app/data/recovered_transcripts/PROVENANCE.md.
--
-- This table is the only thing this surface writes to.

CREATE TABLE IF NOT EXISTS quartet_dose_response_queue (
    id BIGSERIAL PRIMARY KEY,
    session_label TEXT NOT NULL DEFAULT 'quartet_dose_response_v1',
    scenario_id TEXT NOT NULL CHECK (scenario_id IN ('AQ-1', 'AQ-2', 'AQ-G07', 'AQ-G08')),
    section TEXT,
    client_says TEXT,
    condition_label TEXT NOT NULL CHECK (condition_label IN ('before_no_affinity', 'after_affinity_fix')),
    response_text TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('live_snapshot', 'recovered_transcript')),
    original_run_id TEXT,
    text_provenance TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,

    -- Scoring (capability-track rubric + move-level checklist)
    primary_score INTEGER CHECK (primary_score IS NULL OR primary_score BETWEEN 0 AND 3),
    accuracy_score INTEGER CHECK (accuracy_score IS NULL OR accuracy_score BETWEEN 0 AND 3),
    naturalness_score INTEGER CHECK (naturalness_score IS NULL OR naturalness_score BETWEEN 0 AND 3),
    safety_veto TEXT CHECK (safety_veto IS NULL OR safety_veto IN ('ok', 'fail')),
    spine_moves JSONB,
    moves_present_count INTEGER,
    notes TEXT,

    human_scored BOOLEAN NOT NULL DEFAULT FALSE,
    rater_id TEXT,
    scored_at TIMESTAMPTZ,
    score_latency_ms INTEGER,
    score_session_id TEXT,
    gold_admin_run_id TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (session_label, scenario_id, condition_label)
);

CREATE INDEX IF NOT EXISTS idx_qdrq_session_sort
    ON quartet_dose_response_queue (session_label, sort_order);

COMMENT ON TABLE quartet_dose_response_queue IS
    'Scoring-only queue for the AQ-1/AQ-2/AQ-G07/AQ-G08 before/after affinity-fix '
    'dose-response comparison. Never sourced from or written back into '
    'six_quotient_human_gold — see backend/app/routers/quartet_dose_response_api.py';
COMMENT ON COLUMN quartet_dose_response_queue.spine_moves IS
    'JSONB: {"<move_id>": {"value": "present|partial|absent", "reason": "<one word, partial only>"}, ...}';
COMMENT ON COLUMN quartet_dose_response_queue.source IS
    'live_snapshot = copied read-only from six_quotient_human_gold.nate_response_live at seed time; '
    'recovered_transcript = ingested from a text file because the DB row was overwritten by a later regen';

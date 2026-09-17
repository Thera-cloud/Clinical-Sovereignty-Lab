-- QUANTUM-CRYSTAL-ARCH: Coach practice snapshot + consult archive (additive)
-- folder_type 'assistant' = master's file drawer for an assistant coach
-- Reports never persist client names (metrics + LN guidance only)

ALTER TABLE coach_folders DROP CONSTRAINT IF EXISTS coach_folders_folder_type_check;
ALTER TABLE coach_folders ADD CONSTRAINT coach_folders_folder_type_check
    CHECK (folder_type IN ('personal', 'client', 'family', 'group', 'company', 'assistant'));

ALTER TABLE coach_consultations ADD COLUMN IF NOT EXISTS session_id TEXT;
ALTER TABLE coach_consultations ADD COLUMN IF NOT EXISTS transcript_text TEXT;
ALTER TABLE coach_consultations ADD COLUMN IF NOT EXISTS folder_file_id UUID;
ALTER TABLE coach_consultations ADD COLUMN IF NOT EXISTS nate_summary TEXT;
ALTER TABLE coach_consultations ADD COLUMN IF NOT EXISTS action_items JSONB DEFAULT '[]'::jsonb;
ALTER TABLE coach_consultations ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS assistant_consult_action_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    master_username TEXT NOT NULL,
    assistant_username TEXT NOT NULL,
    consult_session_id TEXT,
    item_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'completed', 'dropped')),
    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    source TEXT NOT NULL DEFAULT 'consult_transcript',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_consult_actions_pair
    ON assistant_consult_action_items (master_username, assistant_username, status);

CREATE TABLE IF NOT EXISTS coach_practice_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coach_username TEXT NOT NULL,
    master_username TEXT,
    window_days INTEGER NOT NULL,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    guidance JSONB NOT NULL DEFAULT '{}'::jsonb,
    html TEXT NOT NULL,
    folder_file_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_practice_reports_coach
    ON coach_practice_reports (coach_username, created_at DESC);

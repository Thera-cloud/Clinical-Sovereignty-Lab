-- Mirror Capture chapters on existing coach_voice_recordings. Additive only.
-- QUANTUM-CRYSTAL-ARCH

ALTER TABLE coach_voice_recordings
    ADD COLUMN IF NOT EXISTS capture_part_index INT;

ALTER TABLE coach_voice_recordings
    ADD COLUMN IF NOT EXISTS capture_kind TEXT;

ALTER TABLE coach_voice_recordings
    ADD COLUMN IF NOT EXISTS clone_consent BOOLEAN NOT NULL DEFAULT FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS idx_coach_voice_mirror_part_live
    ON coach_voice_recordings (coach_id, capture_kind)
    WHERE capture_kind IS NOT NULL;

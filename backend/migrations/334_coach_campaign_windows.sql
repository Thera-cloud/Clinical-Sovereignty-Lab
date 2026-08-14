-- Additive: coach-self interview + campaign windows (A–E). No DROP.
ALTER TABLE coach_voice_recordings
  ALTER COLUMN client_id DROP NOT NULL;
ALTER TABLE coach_voice_recordings
  ADD COLUMN IF NOT EXISTS media_kind TEXT NOT NULL DEFAULT 'audio';
ALTER TABLE coach_voice_recordings
  ADD COLUMN IF NOT EXISTS subject TEXT NOT NULL DEFAULT 'client';

ALTER TABLE coach_voice_profile
  ADD COLUMN IF NOT EXISTS style_json JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE coach_voice_profile
  ADD COLUMN IF NOT EXISTS source_recording_id UUID;

ALTER TABLE coach_marketing_campaigns
  ADD COLUMN IF NOT EXISTS length_days INT NOT NULL DEFAULT 1;
ALTER TABLE coach_marketing_campaigns
  ADD COLUMN IF NOT EXISTS audience TEXT NOT NULL DEFAULT 'clients';

ALTER TABLE marketing_content
  ADD COLUMN IF NOT EXISTS scheduled_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_coach_voice_rec_subject
  ON coach_voice_recordings (coach_id, subject, created_at DESC);

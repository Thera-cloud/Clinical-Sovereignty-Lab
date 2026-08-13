-- Additive voice-campaign tables (Seam 3 C0). No table removal.
CREATE TABLE IF NOT EXISTS coach_voice_profile (
    coach_id VARCHAR PRIMARY KEY,
    notes TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS coach_voice_recordings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coach_id VARCHAR NOT NULL,
    client_id VARCHAR NOT NULL,
    r2_key TEXT NOT NULL,
    audio_ciphertext TEXT,
    transcript_ciphertext TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_coach_voice_rec_coach
  ON coach_voice_recordings (coach_id, created_at DESC);

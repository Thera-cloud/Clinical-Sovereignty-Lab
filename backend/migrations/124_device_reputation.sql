-- Migration 124: Device Reputation Table
-- Tracks per-device behavioral reputation for the Distributed Defense Shield (Layer 4).
-- Devices that submit garbage crystals accumulate low reputation scores and can be quarantined.

CREATE TABLE IF NOT EXISTS device_reputation (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id VARCHAR(255) NOT NULL UNIQUE,
    user_id VARCHAR(255) NOT NULL,
    reputation_score FLOAT DEFAULT 1.0 CHECK (reputation_score >= 0.0 AND reputation_score <= 1.0),
    crystal_quality_avg FLOAT DEFAULT 0.0,
    submissions_total INTEGER DEFAULT 0,
    submissions_rejected INTEGER DEFAULT 0,
    last_activity_at TIMESTAMPTZ DEFAULT NOW(),
    quarantined BOOLEAN DEFAULT FALSE,
    quarantine_reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_device_reputation_user_id ON device_reputation(user_id);
CREATE INDEX IF NOT EXISTS idx_device_reputation_quarantined ON device_reputation(quarantined);

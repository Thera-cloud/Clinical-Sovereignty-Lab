-- Migration 143: Timezone Localization
-- Adds client_timezone context to all clinical event records.
-- UTC remains the storage timestamp; client_timezone enables
-- reconstruction of the client's local time of interaction.
-- Required for HIPAA-compliant audit precision and to prevent
-- false positives in community aggregation models.

-- conversation_history: every AI interaction
ALTER TABLE conversation_history
  ADD COLUMN IF NOT EXISTS client_timezone TEXT DEFAULT 'UTC',
  ADD COLUMN IF NOT EXISTS utc_offset_minutes INTEGER;

-- nevedal_metrics: every C_emo measurement
ALTER TABLE nevedal_metrics
  ADD COLUMN IF NOT EXISTS client_timezone TEXT DEFAULT 'UTC';

-- audit_log: every admin/system action
ALTER TABLE audit_log
  ADD COLUMN IF NOT EXISTS client_timezone TEXT DEFAULT 'UTC';

-- community_check_ins: group session attendance
ALTER TABLE community_check_ins
  ADD COLUMN IF NOT EXISTS client_timezone TEXT DEFAULT 'UTC';

-- coaching_sessions: scheduled and live sessions
ALTER TABLE coaching_sessions
  ADD COLUMN IF NOT EXISTS client_timezone TEXT DEFAULT 'UTC';

-- nate_intelligence_crystals: knowledge synthesis metadata
ALTER TABLE nate_intelligence_crystals
  ADD COLUMN IF NOT EXISTS timezone_spread TEXT[];

-- skyeye_activity: platform activity log
ALTER TABLE skyeye_activity
  ADD COLUMN IF NOT EXISTS client_timezone TEXT;

-- liminal_sessions: liminal presence tracking
DO $$ BEGIN
  ALTER TABLE liminal_sessions
    ADD COLUMN IF NOT EXISTS client_timezone TEXT DEFAULT 'UTC';
EXCEPTION WHEN undefined_table THEN NULL;
END $$;

COMMENT ON COLUMN conversation_history.client_timezone IS 'IANA timezone of client at interaction time (e.g. America/Los_Angeles)';
COMMENT ON COLUMN conversation_history.utc_offset_minutes IS 'UTC offset in minutes at interaction time (e.g. -420 for PDT)';
COMMENT ON COLUMN nevedal_metrics.client_timezone IS 'IANA timezone of client during biometric measurement';
COMMENT ON COLUMN nate_intelligence_crystals.timezone_spread IS 'Distinct client timezones contributing to this crystal cluster';

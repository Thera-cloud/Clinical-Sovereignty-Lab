-- Out-of-office rows override coach_availability. Additive only.
ALTER TABLE google_external_busy
    ADD COLUMN IF NOT EXISTS event_type TEXT;

COMMENT ON COLUMN google_external_busy.event_type IS
    'Google Calendar eventType. outOfOffice blocks coach appointment slots for the whole window.';

-- Prior tokens were issued without eventTypes=outOfOffice. Drop them so the
-- next agent cycle does a full pull and stores all-day out-of-office windows.
UPDATE google_calendar_connection SET sync_token = NULL WHERE sync_token IS NOT NULL;
UPDATE google_workspace_connection SET sync_token = NULL WHERE sync_token IS NOT NULL;

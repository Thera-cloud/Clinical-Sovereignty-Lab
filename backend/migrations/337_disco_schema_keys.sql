-- 337_disco_schema_keys.sql
-- Retroactive key map after 336. Additive only. No flags. No DROP.
-- Spec coaches(id) / google_credentials are NOT live.

BEGIN;

ALTER TABLE disco_content_topics ADD COLUMN IF NOT EXISTS source_url TEXT;
ALTER TABLE disco_content_topics ADD COLUMN IF NOT EXISTS used_in TEXT;

CREATE TABLE IF NOT EXISTS disco_schema_key_map (
    contract     TEXT NOT NULL,
    spec_name    TEXT NOT NULL,
    live_table   TEXT NOT NULL,
    live_column  TEXT NOT NULL,
    notes        TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (contract, spec_name)
);

INSERT INTO disco_schema_key_map (contract, spec_name, live_table, live_column, notes) VALUES
('credentials', 'coaches.id', 'users', 'username', 'No coaches table. Public coach_id = users.username'),
('credentials', 'coaches.hardware_id', 'users', 'hardware_id', 'Device id only; disco identity stays username'),
('credentials', 'relationship_class', 'users', 'relationship_class', 'coaching vs clinical register'),
('credentials', 'client_jurisdiction', 'users', 'client_jurisdiction', ''),
('credentials', 'vault_sync', 'users', 'vault_sync', ''),
('credentials', 'coach_credentials.coach_id', 'coach_credentials', 'coach_id', 'VARCHAR username, not UUID'),
('credentials', 'google_credentials', 'google_workspace_connection', 'user_id', 'Tokens: workspace + calendar, never google_credentials'),
('credentials', 'google_calendar', 'google_calendar_connection', 'user_id', 'users.username'),
('engagements', 'campaign_engagements.coach_id', 'campaign_engagements', 'coach_id', 'users.username'),
('engagements', 'channel', 'campaign_engagements', 'channel', '336 widen'),
('engagements', 'payload', 'campaign_engagements', 'payload', '336 widen'),
('content_topics', 'content_topics', 'content_topics', 'topic', 'v1.5 newsletter topics'),
('content_topics', 'coach_flagged', 'disco_content_topics', 'coach_id', 'Coach-flagged overlay; coach_id = username'),
('authoring', 'LN authoring pipeline', 'marketing_content', 'id', 'status/slug/coach_id'),
('authoring', 'marketing_content.coach_id', 'marketing_content', 'coach_id', 'users.username'),
('identity', 'canonical_identity.coach_id', 'canonical_identity', 'coach_id', 'PK = users.username')
ON CONFLICT (contract, spec_name) DO UPDATE SET
    live_table = EXCLUDED.live_table,
    live_column = EXCLUDED.live_column,
    notes = EXCLUDED.notes;

COMMENT ON TABLE canonical_identity IS 'coach_id = users.username; not coaches(id)';
COMMENT ON COLUMN canonical_identity.coach_id IS 'users.username';
COMMENT ON TABLE disco_content_topics IS 'Coach-flagged topics. coach_id = users.username';
COMMENT ON TABLE disco_schema_key_map IS 'Spec name → live table.column. Forbidden: google_credentials, coaches';

COMMIT;

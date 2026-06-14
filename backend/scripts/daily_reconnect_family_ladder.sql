-- Daily Reconnect: family escalation ladder reconstruction (spec §10)
-- Run: psql -U nate_admin -d little_nate -f backend/scripts/daily_reconnect_family_ladder.sql

SELECT
    s.family_id,
    s.id AS session_id,
    s.state,
    s.total_reconnects,
    s.soft_incident_count,
    s.created_at AS session_started,
    s.closed_at,
    e.event_type,
    e.detail,
    e.created_at AS event_at
FROM daily_reconnect_session s
LEFT JOIN daily_reconnect_event e ON e.session_id = s.id
WHERE s.family_id = :family_id
ORDER BY s.created_at DESC, e.created_at ASC;

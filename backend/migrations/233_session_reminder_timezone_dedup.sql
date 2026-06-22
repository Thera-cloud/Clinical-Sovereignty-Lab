-- Migration 233: Session reminder timezone dedup — expand CHECK constraints
-- Fixes NateCheckInAgent session_reminder_* inserts and session_notifications types.

ALTER TABLE session_notifications
    DROP CONSTRAINT IF EXISTS session_notifications_notification_type_check;

ALTER TABLE session_notifications
    ADD CONSTRAINT session_notifications_notification_type_check
    CHECK (notification_type = ANY (ARRAY[
        'reminder_48h'::text,
        'reminder_72h'::text,
        'reminder_24h'::text,
        'payment_due_72h'::text,
        'payment_failed'::text,
        'cancellation'::text,
        'confirmation'::text
    ]));

ALTER TABLE nate_checkins
    DROP CONSTRAINT IF EXISTS nate_checkins_checkin_type_check;

ALTER TABLE nate_checkins
    ADD CONSTRAINT nate_checkins_checkin_type_check
    CHECK (checkin_type::text = ANY (ARRAY[
        'coach_alert_62h'::character varying,
        'client_72h'::character varying,
        'coach_72h'::character varying,
        'session_reminder_72h'::character varying,
        'session_reminder_24h'::character varying,
        'coach_request_escalation'::character varying
    ]::text[]));

ALTER TABLE nate_checkins
    DROP CONSTRAINT IF EXISTS nate_checkins_role_check;

ALTER TABLE nate_checkins
    ADD CONSTRAINT nate_checkins_role_check
    CHECK (role::text = ANY (ARRAY[
        'CLIENT'::character varying,
        'COACH'::character varying,
        'SYSTEM'::character varying
    ]::text[]));

INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES ('nate_checkin_check_count', '{"expected": 9}'::jsonb)
ON CONFLICT (parameter_key) DO UPDATE
SET parameter_value = EXCLUDED.parameter_value;

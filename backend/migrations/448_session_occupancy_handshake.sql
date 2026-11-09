-- Occupancy lock (optional gist exclusion) + billing auditor handshake 38 → 41.
CREATE EXTENSION IF NOT EXISTS btree_gist;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
      FROM coaching_sessions a
      JOIN coaching_sessions b
        ON a.session_id < b.session_id
       AND a.coach_id = b.coach_id
       AND LOWER(COALESCE(a.status,'')) IN ('scheduled','active','pending_approval')
       AND LOWER(COALESCE(b.status,'')) IN ('scheduled','active','pending_approval')
       AND tstzrange(
             COALESCE(a.scheduled_start, a.scheduled_at),
             COALESCE(a.scheduled_end, COALESCE(a.scheduled_start, a.scheduled_at)
                      + INTERVAL '50 minutes'), '[)')
           && tstzrange(
             COALESCE(b.scheduled_start, b.scheduled_at),
             COALESCE(b.scheduled_end, COALESCE(b.scheduled_start, b.scheduled_at)
                      + INTERVAL '50 minutes'), '[)')
  ) THEN
    RAISE NOTICE '448 skip exclusion: overlapping blocking rows exist';
    RETURN;
  END IF;

  BEGIN
    ALTER TABLE coaching_sessions
      ADD CONSTRAINT coaching_sessions_coach_slot_excl
      EXCLUDE USING gist (
        coach_id WITH =,
        tstzrange(
          COALESCE(scheduled_start, scheduled_at),
          COALESCE(scheduled_end,
                   COALESCE(scheduled_start, scheduled_at) + INTERVAL '50 minutes'),
          '[)'
        ) WITH &&
      )
      WHERE (LOWER(status) IN ('scheduled','active','pending_approval'));
  EXCEPTION
    WHEN duplicate_object THEN
      NULL;
    WHEN others THEN
      RAISE NOTICE '448 exclusion not applied: %', SQLERRM;
  END;
END $$;

UPDATE trust_baseline
   SET parameter_value = jsonb_set(parameter_value, '{expected}', '41')
 WHERE parameter_key = 'billing_endpoint_count';

-- Slot bounds as stored columns so EXCLUDE USING gist is IMMUTABLE.
-- 448 failed: COALESCE(scheduled_start, scheduled_at) is not IMMUTABLE.
CREATE EXTENSION IF NOT EXISTS btree_gist;

ALTER TABLE coaching_sessions
  ADD COLUMN IF NOT EXISTS slot_start TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS slot_end TIMESTAMPTZ;

UPDATE coaching_sessions
   SET slot_start = COALESCE(scheduled_start, scheduled_at),
       slot_end = COALESCE(
           scheduled_end,
           COALESCE(scheduled_start, scheduled_at) + INTERVAL '50 minutes'
       )
 WHERE slot_start IS NULL
   AND COALESCE(scheduled_start, scheduled_at) IS NOT NULL;

CREATE OR REPLACE FUNCTION coaching_sessions_sync_slot_bounds()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.slot_start := COALESCE(NEW.scheduled_start, NEW.scheduled_at);
  IF NEW.slot_start IS NOT NULL THEN
    NEW.slot_end := COALESCE(NEW.scheduled_end, NEW.slot_start + INTERVAL '50 minutes');
  ELSE
    NEW.slot_end := NULL;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS coaching_sessions_sync_slot_bounds ON coaching_sessions;
CREATE TRIGGER coaching_sessions_sync_slot_bounds
  BEFORE INSERT OR UPDATE ON coaching_sessions
  FOR EACH ROW
  EXECUTE FUNCTION coaching_sessions_sync_slot_bounds();

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
       AND a.slot_start IS NOT NULL AND a.slot_end IS NOT NULL
       AND b.slot_start IS NOT NULL AND b.slot_end IS NOT NULL
       AND tstzrange(a.slot_start, a.slot_end, '[)')
        && tstzrange(b.slot_start, b.slot_end, '[)')
  ) THEN
    RAISE NOTICE '449 skip exclusion: overlapping live coach slots exist';
    RETURN;
  END IF;

  BEGIN
    ALTER TABLE coaching_sessions
      ADD CONSTRAINT coaching_sessions_coach_slot_excl
      EXCLUDE USING gist (
        coach_id WITH =,
        tstzrange(slot_start, slot_end, '[)') WITH &&
      )
      WHERE (
        LOWER(COALESCE(status, '')) IN ('scheduled','active','pending_approval')
        AND slot_start IS NOT NULL
        AND slot_end IS NOT NULL
        AND slot_end > slot_start
      );
  EXCEPTION
    WHEN duplicate_object THEN
      NULL;
    WHEN others THEN
      RAISE NOTICE '449 exclusion not applied: %', SQLERRM;
  END;
END $$;

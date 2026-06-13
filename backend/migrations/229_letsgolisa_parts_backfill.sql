-- ─────────────────────────────────────────────────────────────────────
-- Migration 229 — LetsGoLisa IFS Parts Backfill (Sensitive Bridge v1.4)
-- ─────────────────────────────────────────────────────────────────────
-- Manual backfill of four IFS parts that LetsGoLisa named for herself
-- during transcript-reviewed sessions (2026-06-10 through 2026-06-13).
-- The Sensitive Bridge auto-extractor (parts_auto_extractor.py) was
-- introduced in the same change set; this migration recovers the parts
-- that were named BEFORE the extractor was wired so the assigned coach
-- (CoachN) can see them in the parts registry immediately.
--
-- Additive only. ON CONFLICT prevents double-insertion if the
-- extractor catches them after deploy. Re-running this migration is
-- safe; it will simply re-activate retired rows.
-- ─────────────────────────────────────────────────────────────────────

BEGIN;

-- Sanity guard: only proceed if LetsGoLisa exists and is enrolled.
DO $$
DECLARE
    v_exists BOOLEAN;
    v_enrolled BOOLEAN;
BEGIN
    SELECT EXISTS(SELECT 1 FROM users WHERE username = 'LetsGoLisa')
      INTO v_exists;
    IF NOT v_exists THEN
        RAISE EXCEPTION 'LetsGoLisa user not found — aborting backfill';
    END IF;

    SELECT EXISTS(
        SELECT 1 FROM sensitive_bridge_enrollment
         WHERE user_id = 'LetsGoLisa'
           AND COALESCE(cohort_label, 'unenrolled') <> 'unenrolled'
    ) INTO v_enrolled;
    IF NOT v_enrolled THEN
        RAISE EXCEPTION 'LetsGoLisa not enrolled in Sensitive Bridge — aborting backfill';
    END IF;
END $$;

INSERT INTO user_parts_registry (
    user_id, part_name, part_number, part_category,
    addiction_link, description, protected_exile_part_id,
    is_active, created_by, client_initiated
) VALUES
    ('LetsGoLisa', 'Lonely Girl', 1, 'exile',
     NULL,
     'Exile that felt unwanted; surfaced during family-of-origin trauma work. '
     'Client named her in session ("I called her Lonely girl"). Holds isolation '
     'and unworthiness affect.',
     NULL, TRUE, 'manual_backfill_2026_06_13_transcript_review', TRUE),

    ('LetsGoLisa', 'Scolded Girl', 2, 'exile',
     NULL,
     'Exile that hid and shrank from conflict. Client described her as the part '
     'that "hid and shrank from conflict." Holds shame and conflict-avoidance.',
     NULL, TRUE, 'manual_backfill_2026_06_13_transcript_review', TRUE),

    ('LetsGoLisa', 'The Silencer', 3, 'protector',
     NULL,
     'Protector who was angry with the exiled parts for being weak. Client said: '
     '"there was also a protector who was angry with the others for being weak '
     'so I called that one the Silencer." Manages by silencing vulnerable parts.',
     NULL, TRUE, 'manual_backfill_2026_06_13_transcript_review', TRUE),

    ('LetsGoLisa', 'The Archivist', 4, 'manager',
     NULL,
     'Manager who holds the family story and narrative timeline. Keeper of '
     'memory and chronology; organizes meaning. Helps integrate younger parts '
     'when Jesus visits them (per client''s use of "He Came For All My Parts" '
     'by Kristy Moore as a frame for parts work).',
     NULL, TRUE, 'manual_backfill_2026_06_13_transcript_review', TRUE)

ON CONFLICT (user_id, part_name) DO UPDATE
   SET is_active = TRUE,
       retired_at = NULL,
       part_category = EXCLUDED.part_category,
       description = EXCLUDED.description;

-- Audit each insert (idempotent: one row per part_name written today).
INSERT INTO sensitive_bridge_log (
    user_id, event_type, event_severity,
    payload_json, access_classification, recorded_by,
    pii_screened_at, redaction_pass_count
)
SELECT
    'LetsGoLisa',
    'part_client_initiated',
    'info',
    jsonb_build_object(
        'event_type', 'part_client_initiated',
        'part_name', p.part_name,
        'part_category', p.part_category,
        'auto_extracted', FALSE,
        'extraction_method', 'manual_backfill_transcript_review',
        'reason', 'parts_named_before_auto_extractor_wired',
        'registry_id', p.id
    ),
    'clinician_and_admin',
    'migration_229_letsgolisa_backfill',
    NOW(),
    1
FROM user_parts_registry p
WHERE p.user_id = 'LetsGoLisa'
  AND p.part_name IN ('Lonely Girl', 'Scolded Girl', 'The Silencer', 'The Archivist')
  AND NOT EXISTS (
      SELECT 1 FROM sensitive_bridge_log l
       WHERE l.user_id = 'LetsGoLisa'
         AND l.event_type = 'part_client_initiated'
         AND l.payload_json->>'part_name' = p.part_name
         AND l.recorded_by = 'migration_229_letsgolisa_backfill'
  );

COMMIT;

-- Verification (post-commit, read-only):
-- SELECT id, part_name, part_category, is_active, created_by, client_initiated
--   FROM user_parts_registry
--  WHERE user_id = 'LetsGoLisa'
--  ORDER BY part_number;

-- Bind existing CoachN Studio DID. Does not purchase. Additive. QUANTUM-CRYSTAL-ARCH

UPDATE studio_shows
SET did_e164 = '+15617833006', updated_at = NOW()
WHERE coach_id = 'COACH_COACHN_ID'
  AND (did_e164 IS NULL OR did_e164 = '');

CREATE UNIQUE INDEX IF NOT EXISTS studio_shows_did_e164_uidx
    ON studio_shows (did_e164)
    WHERE did_e164 IS NOT NULL AND did_e164 <> '';

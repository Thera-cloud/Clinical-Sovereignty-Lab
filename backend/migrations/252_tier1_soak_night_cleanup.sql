-- QUANTUM-CRYSTAL-ARCH — D.14b: one qualifying nightly row per UTC calendar day
-- Marks same-day duplicate nightly trend rows as smoke (keeps earliest).

UPDATE six_quotient_theta_trend t
SET is_smoke = TRUE
WHERE t.run_kind = 'nightly'
  AND COALESCE(t.is_smoke, FALSE) = FALSE
  AND t.id NOT IN (
    SELECT DISTINCT ON (((created_at AT TIME ZONE 'UTC')::date)) id
    FROM six_quotient_theta_trend
    WHERE run_kind = 'nightly'
    ORDER BY ((created_at AT TIME ZONE 'UTC')::date), created_at ASC, id ASC
  );

COMMENT ON COLUMN six_quotient_theta_trend.is_smoke IS
  'Non-qualifying: smoke triggers, short packs, or same-day duplicate nightlies';

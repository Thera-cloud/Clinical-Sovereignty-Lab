-- Backfill promotional_specials.current_redemptions from historical usage.
-- Additive only: never lowers counts; does not modify users or subscriptions.

WITH pending_counts AS (
    SELECT UPPER(TRIM(discount_code)) AS code, COUNT(*)::int AS cnt
    FROM pending_signups
    WHERE status = 'completed'
      AND discount_code IS NOT NULL
      AND TRIM(discount_code) <> ''
    GROUP BY 1
),
user_counts AS (
    SELECT UPPER(TRIM(profile_data->>'discount_code')) AS code,
           COUNT(DISTINCT username)::int AS cnt
    FROM users
    WHERE profile_data->>'discount_code' IS NOT NULL
      AND TRIM(profile_data->>'discount_code') <> ''
    GROUP BY 1
),
merged AS (
    SELECT code, MAX(cnt) AS cnt
    FROM (
        SELECT code, cnt FROM pending_counts
        UNION ALL
        SELECT code, cnt FROM user_counts
    ) u
    GROUP BY code
)
UPDATE promotional_specials ps
SET current_redemptions = GREATEST(ps.current_redemptions, merged.cnt)
FROM merged
WHERE UPPER(ps.promo_code) = merged.code
  AND ps.current_redemptions < merged.cnt;

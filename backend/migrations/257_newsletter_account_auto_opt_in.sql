-- QUANTUM-CRYSTAL-ARCH — Little Nate Dispatch account auto opt-in backfill
-- Opt every users.profile_data email into newsletter_subscribers as active.
-- Never override unsubscribed or suppressed. Promote pending → active.

INSERT INTO newsletter_subscribers (
    email,
    status,
    unsubscribe_token_hash,
    consent_delivery_at,
    consent_scope,
    source
)
SELECT DISTINCT ON (LOWER(TRIM(u.profile_data->>'email')))
    LOWER(TRIM(u.profile_data->>'email')),
    'active',
    encode(sha256(convert_to(gen_random_uuid()::text, 'UTF8')), 'hex'),
    NOW(),
    'delivery',
    'account_backfill'
FROM users u
WHERE u.profile_data->>'email' IS NOT NULL
  AND TRIM(u.profile_data->>'email') LIKE '%@%'
  AND POSITION('@' IN TRIM(u.profile_data->>'email')) > 1
ORDER BY LOWER(TRIM(u.profile_data->>'email')), u.created_at DESC NULLS LAST
ON CONFLICT (email) DO UPDATE SET
    status = CASE
        WHEN newsletter_subscribers.status IN ('unsubscribed', 'suppressed')
            THEN newsletter_subscribers.status
        ELSE 'active'
    END,
    unsubscribe_token_hash = COALESCE(
        newsletter_subscribers.unsubscribe_token_hash,
        EXCLUDED.unsubscribe_token_hash
    ),
    consent_delivery_at = CASE
        WHEN newsletter_subscribers.status IN ('unsubscribed', 'suppressed')
            THEN newsletter_subscribers.consent_delivery_at
        ELSE COALESCE(
            newsletter_subscribers.consent_delivery_at,
            EXCLUDED.consent_delivery_at
        )
    END,
    source = CASE
        WHEN newsletter_subscribers.status IN ('unsubscribed', 'suppressed')
            THEN newsletter_subscribers.source
        WHEN newsletter_subscribers.source IS NULL
            OR btrim(newsletter_subscribers.source) = ''
            THEN EXCLUDED.source
        ELSE newsletter_subscribers.source
    END,
    updated_at = NOW();

-- ============================================================================
-- Migration 221: user_creation_events — unified audit log for every users INSERT
--
-- Purpose
--   Single source of truth for "an account was created," regardless of which
--   code path created it (WS register_request, Stripe webhook,
--   registration_finalize, manual SQL, admin tools). Solves the observability
--   gap identified during the 2026-05-17 support@-notification investigation.
--
-- Design constraints (WJR safety — see .cursorrules destructive-ops gate)
--   1. ADDITIVE ONLY. No ALTER on existing tables, no DROP.
--   2. TRIGGER MUST NEVER FAIL THE PARENT INSERT. Every block in
--      notify_new_user_created() is wrapped in EXCEPTION WHEN OTHERS so a
--      bug in audit logic can never block a signup.
--   3. Backfill existing users.* with processed_at=NOW() so the reconciler
--      does not flood support@ with historical rows on first deploy.
-- ============================================================================

CREATE TABLE IF NOT EXISTS user_creation_events (
    id              BIGSERIAL PRIMARY KEY,
    username        TEXT NOT NULL,
    role            TEXT,
    tier            TEXT,
    hardware_id     TEXT,
    user_db_id      UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_via     TEXT NOT NULL DEFAULT 'unknown',
    source_metadata JSONB DEFAULT '{}'::jsonb,
    processed_at    TIMESTAMPTZ,
    processed_by    TEXT,
    notification_sent  BOOLEAN NOT NULL DEFAULT FALSE,
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_user_creation_events_unprocessed
    ON user_creation_events (created_at)
    WHERE processed_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_user_creation_events_username
    ON user_creation_events (LOWER(username));

CREATE INDEX IF NOT EXISTS idx_user_creation_events_created_via
    ON user_creation_events (created_via, created_at DESC);

-- ----------------------------------------------------------------------------
-- Exception-safe trigger function. Failure here MUST NOT block the users
-- INSERT (no rollback, no exception bubbling). Trigger writes the audit row;
-- the reconciler agent decides what to do with it later.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION notify_new_user_created()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    _via TEXT;
BEGIN
    BEGIN
        -- Allow a code path to set its own provenance label via
        --   SET LOCAL myapp.user_creation_via = 'ws_register'
        -- inside the same transaction. Falls back to 'unknown' (which is the
        -- reconciler's signal that this row came from a path that does not
        -- yet call account_creation_hook — i.e. manual SQL or bulk import).
        BEGIN
            _via := current_setting('myapp.user_creation_via', TRUE);
        EXCEPTION WHEN OTHERS THEN
            _via := NULL;
        END;
        IF _via IS NULL OR _via = '' THEN
            _via := 'unknown';
        END IF;

        INSERT INTO user_creation_events (
            username, role, tier, hardware_id, user_db_id,
            created_via, source_metadata
        ) VALUES (
            NEW.username,
            NEW.role,
            NEW.tier,
            NEW.hardware_id,
            NEW.id,
            _via,
            jsonb_build_object(
                'has_email',           (NEW.email IS NOT NULL AND NEW.email <> ''),
                'has_phone',           (NEW.phone IS NOT NULL AND NEW.phone <> ''),
                'has_joined_date',     (NEW.profile_data ? 'joined_date'),
                'has_stripe_customer', (NEW.profile_data ? 'stripe_customer_id'
                                        AND COALESCE(NEW.profile_data->>'stripe_customer_id','') <> ''),
                'subscription_status', COALESCE(NEW.subscription_status, ''),
                'token_balance',       COALESCE(NEW.token_balance, 0)
            )
        );

        -- pg_notify is best-effort. If no listener attached, NOTIFY just queues.
        PERFORM pg_notify('user_created', json_build_object(
            'username', NEW.username,
            'role',     NEW.role,
            'tier',     NEW.tier
        )::text);

    EXCEPTION WHEN OTHERS THEN
        -- SWALLOW. Never block the user INSERT. The trigger failing must not
        -- prevent a real client from registering during the WJR campaign.
        RAISE WARNING 'notify_new_user_created trigger failed for %: %',
            NEW.username, SQLERRM;
    END;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_user_created ON users;
CREATE TRIGGER on_user_created
    AFTER INSERT ON users
    FOR EACH ROW
    EXECUTE FUNCTION notify_new_user_created();

-- ----------------------------------------------------------------------------
-- Backfill: mark every pre-existing users row as already processed so the
-- reconciler does not flood support@ on first deploy with historical orphans.
-- ----------------------------------------------------------------------------
INSERT INTO user_creation_events (
    username, role, tier, hardware_id, user_db_id,
    created_at, created_via, source_metadata,
    processed_at, processed_by
)
SELECT
    u.username,
    u.role,
    u.tier,
    u.hardware_id,
    u.id,
    COALESCE(u.created_at, NOW()),
    'backfill_migration_221',
    jsonb_build_object('backfill', true),
    NOW(),
    'migration_221_backfill'
FROM users u
WHERE NOT EXISTS (
    SELECT 1 FROM user_creation_events e
    WHERE LOWER(e.username) = LOWER(u.username)
);

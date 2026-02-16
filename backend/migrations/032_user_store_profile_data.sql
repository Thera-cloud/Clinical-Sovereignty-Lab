-- =============================================================================
-- Migration 030: Add profile_data JSONB column for UserStore
-- =============================================================================
-- Adds a profile_data JSONB column to the users table. This stores the full
-- profile dict from the old user_registry.json format, preserving all extra
-- fields that don't have dedicated columns (token_balance, dojo_subscriptions,
-- assigned_coach, etc.).
--
-- The UserStore reads from profile_data and overlays indexed columns (role,
-- email, hardware_id, etc.) on top, so the indexed columns remain the source
-- of truth for queries while profile_data holds the complete profile.
-- =============================================================================

-- Add profile_data column (idempotent)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'profile_data'
    ) THEN
        ALTER TABLE users ADD COLUMN profile_data JSONB DEFAULT '{}'::jsonb;
        RAISE NOTICE 'Added profile_data column to users table';
    END IF;
END $$;

-- Add phone column if missing
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'phone'
    ) THEN
        ALTER TABLE users ADD COLUMN phone VARCHAR(30) DEFAULT '';
    END IF;
END $$;

-- Add token_balance column if missing
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'token_balance'
    ) THEN
        ALTER TABLE users ADD COLUMN token_balance INTEGER DEFAULT 0;
    END IF;
END $$;

-- Add last_login column if missing
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'last_login'
    ) THEN
        ALTER TABLE users ADD COLUMN last_login TIMESTAMP WITH TIME ZONE;
    END IF;
END $$;

-- Add login_count column if missing
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'login_count'
    ) THEN
        ALTER TABLE users ADD COLUMN login_count INTEGER DEFAULT 0;
    END IF;
END $$;

-- Ensure indexes on commonly-queried columns
CREATE INDEX IF NOT EXISTS idx_users_hardware_id ON users (hardware_id);
CREATE INDEX IF NOT EXISTS idx_users_role ON users (role);
CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);
CREATE INDEX IF NOT EXISTS idx_users_family_id ON users (family_id);
CREATE INDEX IF NOT EXISTS idx_users_subscription_status ON users (subscription_status);

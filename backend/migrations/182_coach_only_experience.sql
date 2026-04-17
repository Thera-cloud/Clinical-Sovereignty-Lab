-- Migration 182: Coach Only Client Experience
-- Creates coach_profiles, coach_requests, coach_messages tables
-- Alters coaching_sessions (add intake_note), coach_availability (add is_blocked)
-- Seeds coach_profiles from existing users WHERE role = 'COACH'

-- 1. coach_profiles — structured coach directory data
CREATE TABLE IF NOT EXISTS coach_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coach_user_id VARCHAR NOT NULL UNIQUE,
    username VARCHAR,
    display_name VARCHAR NOT NULL,
    photo_url TEXT,
    bio TEXT,
    specialty_tags JSONB DEFAULT '[]'::jsonb,
    years_experience INT DEFAULT 0,
    accepting_new_clients BOOLEAN DEFAULT false,
    max_caseload INT DEFAULT 20,
    current_caseload INT DEFAULT 0,
    zoom_link TEXT,
    session_duration_minutes INT DEFAULT 60,
    master_coach_id VARCHAR,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_coach_profiles_accepting
    ON coach_profiles(accepting_new_clients) WHERE accepting_new_clients = true;

-- Seed from existing coaches (accepting_new_clients = false — coaches must opt in)
INSERT INTO coach_profiles (coach_user_id, username, display_name, photo_url, specialty_tags, zoom_link)
SELECT
    hardware_id,
    username,
    COALESCE(profile_data->>'name', username),
    profile_data->>'profile_photo_url',
    COALESCE(
        CASE
            WHEN profile_data->'specialties' IS NOT NULL AND jsonb_typeof(profile_data->'specialties') = 'array'
                THEN profile_data->'specialties'
            WHEN profile_data->'specializations' IS NOT NULL AND jsonb_typeof(profile_data->'specializations') = 'array'
                THEN profile_data->'specializations'
            ELSE '[]'::jsonb
        END,
        '[]'::jsonb
    ),
    profile_data->>'zoom_link'
FROM users
WHERE role = 'COACH'
ON CONFLICT (coach_user_id) DO NOTHING;

-- 2. coach_requests — client-initiated coach selection
CREATE TABLE IF NOT EXISTS coach_requests (
    request_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id VARCHAR NOT NULL,
    client_username VARCHAR,
    coach_user_id VARCHAR NOT NULL,
    intake_note TEXT,
    status VARCHAR NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','accepted','declined','cancelled_by_client')),
    requested_at TIMESTAMPTZ DEFAULT NOW(),
    responded_at TIMESTAMPTZ,
    decline_reason TEXT,
    last_nudge_at TIMESTAMPTZ,
    nudge_count INT DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_coach_requests_active
    ON coach_requests(client_id, coach_user_id)
    WHERE status = 'pending';

CREATE UNIQUE INDEX IF NOT EXISTS idx_coach_requests_one_pending
    ON coach_requests(client_id)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_coach_requests_coach_pending
    ON coach_requests(coach_user_id, status)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_coach_requests_client
    ON coach_requests(client_id, status);

-- 3. coach_messages — pre-acceptance coach-to-client messaging (one-directional v1)
CREATE TABLE IF NOT EXISTS coach_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_id VARCHAR NOT NULL,
    to_id VARCHAR NOT NULL,
    request_id UUID,
    message_text TEXT NOT NULL,
    read_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_coach_messages_to
    ON coach_messages(to_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_coach_messages_request
    ON coach_messages(request_id) WHERE request_id IS NOT NULL;

-- 4. Add intake_note to coaching_sessions
ALTER TABLE coaching_sessions ADD COLUMN IF NOT EXISTS intake_note TEXT;

-- 5. Add is_blocked to coach_availability
ALTER TABLE coach_availability ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN DEFAULT false;

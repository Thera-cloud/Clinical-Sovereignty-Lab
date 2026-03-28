-- Migration 155: Add user_id column to nate_intelligence_crystals
-- Scopes crystals to individual users (NULL = global, set = user-specific)
-- Global firehose crystals remain user_id = NULL and are available to all users.
-- Personal crystals from voice/text sessions get the user's UUID.

ALTER TABLE nate_intelligence_crystals
ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id);

CREATE INDEX IF NOT EXISTS idx_crystals_user_id
ON nate_intelligence_crystals (user_id)
WHERE user_id IS NOT NULL;

COMMENT ON COLUMN nate_intelligence_crystals.user_id IS
    'NULL = global crystal (available to all users). Set = personal crystal scoped to this user only.';

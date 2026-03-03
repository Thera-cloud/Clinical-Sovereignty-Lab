-- Migration 090: Coach Nate Chat History
-- Separate chat history for coach portal Little Nate conversations,
-- isolated from the admin Big Nate chat (skyeye_chat table).

CREATE TABLE IF NOT EXISTS coach_nate_chat_history (
    id BIGSERIAL PRIMARY KEY,
    coach_username VARCHAR(100) NOT NULL,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant')),
    message TEXT NOT NULL,
    mode VARCHAR(50) DEFAULT 'inquiry',
    context_snapshot JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_coach_nate_chat_coach_time
    ON coach_nate_chat_history (coach_username, created_at DESC);

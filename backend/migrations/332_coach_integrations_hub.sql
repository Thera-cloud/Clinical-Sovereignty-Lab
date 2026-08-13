-- Additive Coach Command integrations settings (chat webhook). No table drops.
CREATE TABLE IF NOT EXISTS coach_integrations_settings (
    coach_id VARCHAR PRIMARY KEY,
    chat_webhook_url TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

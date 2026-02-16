-- =============================================================================
-- Migration 036: Webhook Event Idempotency
-- Prevents duplicate processing of webhook events from Stripe, Zoom, Twilio
-- =============================================================================

CREATE TABLE IF NOT EXISTS webhook_events (
    event_id VARCHAR(255) PRIMARY KEY,
    provider VARCHAR(50) NOT NULL,  -- 'stripe', 'zoom', 'twilio'
    event_type VARCHAR(100),
    processed_at TIMESTAMPTZ DEFAULT NOW(),
    payload_hash VARCHAR(64),  -- SHA-256 of payload for verification
    status VARCHAR(20) DEFAULT 'processed'
);

CREATE INDEX IF NOT EXISTS idx_webhook_events_provider ON webhook_events(provider, processed_at DESC);

-- Auto-cleanup events older than 30 days (run via cron or scheduled task)
-- DELETE FROM webhook_events WHERE processed_at < NOW() - INTERVAL '30 days';

-- ============================================================================
-- Migration 013: Stripe Session Packs & Coaching Sessions
-- Creates tables required by stripe_integration.py for session booking
-- and session pack management.
-- ============================================================================

-- Session packs (bundles of coaching sessions purchased via Stripe)
CREATE TABLE IF NOT EXISTS session_packs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    pack_type       VARCHAR(50) NOT NULL DEFAULT 'standard',
    sessions_total  INTEGER NOT NULL DEFAULT 1,
    sessions_remaining INTEGER NOT NULL DEFAULT 1,
    price_cents     INTEGER NOT NULL DEFAULT 0,
    stripe_payment_id VARCHAR(255),
    expires_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_session_packs_user ON session_packs(user_id);
CREATE INDEX IF NOT EXISTS idx_session_packs_expires ON session_packs(expires_at)
    WHERE sessions_remaining > 0;


-- Coaching sessions (individual booked sessions)
CREATE TABLE IF NOT EXISTS coaching_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    coach_id        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    pack_id         UUID REFERENCES session_packs(id) ON DELETE SET NULL,
    scheduled_at    TIMESTAMPTZ NOT NULL,
    price_cents     INTEGER NOT NULL DEFAULT 0,
    status          VARCHAR(30) NOT NULL DEFAULT 'SCHEDULED',
    -- Status values: SCHEDULED, IN_PROGRESS, COMPLETED, CANCELLED, NO_SHOW
    started_at      TIMESTAMPTZ,
    ended_at        TIMESTAMPTZ,
    session_notes   TEXT,
    stripe_payment_intent VARCHAR(255),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_coaching_sessions_client ON coaching_sessions(client_id);
CREATE INDEX IF NOT EXISTS idx_coaching_sessions_coach ON coaching_sessions(coach_id);
CREATE INDEX IF NOT EXISTS idx_coaching_sessions_scheduled ON coaching_sessions(scheduled_at)
    WHERE status = 'SCHEDULED';

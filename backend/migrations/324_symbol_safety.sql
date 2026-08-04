-- Thera-World Global Symbol Safety System — Layer C2/C1 persistence.
-- One row per (user_id, symbol_id) records either a permanent exclusion
-- ("no more snakes") or an explicit opt-in (required before any high-risk
-- symbol — serpent, thorns_crown, mirror_shatter — may ever render).
-- Additive only. Never DROP/ALTER existing tables.

CREATE TABLE IF NOT EXISTS user_symbol_exclusions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    symbol_id TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'excluded' CHECK (state IN ('excluded', 'opted_in', 'opted_in_literal')),
    source TEXT NOT NULL DEFAULT 'conversation',  -- 'conversation' | 'onboarding' | 'admin' | 'codex'
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, symbol_id)
);

CREATE INDEX IF NOT EXISTS idx_user_symbol_exclusions_user
    ON user_symbol_exclusions(user_id);

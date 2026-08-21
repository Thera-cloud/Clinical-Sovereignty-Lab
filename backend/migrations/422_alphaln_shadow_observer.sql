-- Migration 422: AlphaLN Slice 3 — Shadow observer (Loop A seed)
--
-- Additive only. Namespace `alphaln_*`. See cursor rule
-- alphaln-twin-isolation.mdc for invariants.
--
-- Purpose:
--   Shadow observer scores recent Little Nate replies (read from
--   `conversation_history`) and stores an *opinion row* here. AlphaLN never
--   writes to `conversation_history` or `nate_intelligence_crystals` — this
--   table is the twin's shadow ledger.
--
-- Feature flag: ENABLE_ALPHALN_SHADOW_OBSERVER (default false).

CREATE TABLE IF NOT EXISTS alphaln_shadow_observations (
    id                 BIGSERIAL PRIMARY KEY,
    observed_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_table       TEXT NOT NULL,          -- 'conversation_history' | 'sanctuary' | 'coach' etc.
    source_row_id      TEXT,                   -- opaque id/pk for traceability (no PII)
    user_pseudonym     TEXT,                   -- HMAC-tokenized user handle (never raw)
    reply_hash         TEXT NOT NULL,          -- sha256 of the reply text observed
    reply_len          INTEGER NOT NULL DEFAULT 0,
    score              NUMERIC(5,3),           -- twin score (0.000–1.000)
    score_method       TEXT NOT NULL DEFAULT 'heuristic_v1',
    dims               JSONB NOT NULL DEFAULT '{}'::jsonb,  -- per-dimension breakdown
    notes              TEXT,
    metadata           JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_alphaln_shadow_obs_observed
    ON alphaln_shadow_observations(observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_alphaln_shadow_obs_user
    ON alphaln_shadow_observations(user_pseudonym, observed_at DESC);

COMMENT ON TABLE alphaln_shadow_observations IS
    'AlphaLN Slice 3 shadow observations of ANI replies. Read-only ledger; no PII.';

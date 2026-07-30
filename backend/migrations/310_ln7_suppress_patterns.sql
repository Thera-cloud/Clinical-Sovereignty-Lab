-- 30-day reverse suppress patterns (E8 / W18).
-- QUANTUM-CRYSTAL-ARCH
-- Additive only.

CREATE TABLE IF NOT EXISTS ln7_suppress_patterns (
    pattern_key     TEXT PRIMARY KEY,
    until_ts        TIMESTAMPTZ NOT NULL,
    reason          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Partial predicates cannot use NOW() (not IMMUTABLE); filter at query time.
CREATE INDEX IF NOT EXISTS idx_ln7_suppress_until
    ON ln7_suppress_patterns (until_ts);

-- SSE Stage 8 — Localization tables

CREATE TABLE IF NOT EXISTS sse_locale_strings (
    locale_id       UUID PRIMARY KEY,
    storyboard_id   TEXT NOT NULL,
    locale          TEXT NOT NULL,
    strings         JSONB NOT NULL,
    translated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (storyboard_id, locale)
);
CREATE INDEX IF NOT EXISTS idx_sse_locale_strings_sb ON sse_locale_strings (storyboard_id);

CREATE TABLE IF NOT EXISTS sse_user_locale (
    user_id     TEXT PRIMARY KEY,
    locale      TEXT NOT NULL DEFAULT 'en',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

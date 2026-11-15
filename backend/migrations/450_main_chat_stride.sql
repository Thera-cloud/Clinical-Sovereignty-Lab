-- Main-chat stride: the client's pinned standing request. Additive; creates one table.
-- No crystal rows are inserted or changed here. The six v4 priority crystals were
-- already archived in production, and the stride contract lives in the prompt core,
-- so nothing in this file affects chat while ENABLE_MAIN_CHAT_STRIDE is off.

CREATE TABLE IF NOT EXISTS main_chat_stride_state (
    username TEXT PRIMARY KEY,
    standing_request TEXT NOT NULL DEFAULT '',
    confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    pending_request TEXT NOT NULL DEFAULT '',
    theraworld_in_chat BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Sovereign Sanctuary — D1 Sandbox Schema for cli-chamberofsecrets
--
-- Nate's creative workspace. All tables use nate_ext_ prefix.
-- Applied via: wrangler d1 execute cli-chamberofsecrets --file=cloudflare/d1/sandbox_schema.sql

-- ── Extension Metadata Registry ──
CREATE TABLE IF NOT EXISTS nate_ext_metadata (
    table_name TEXT PRIMARY KEY,
    extension_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    created_at TEXT NOT NULL,
    row_count INTEGER DEFAULT 0,
    size_bytes INTEGER DEFAULT 0
);

-- ── Formula Computation Results ──
CREATE TABLE IF NOT EXISTS nate_ext_formula_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    formula_name TEXT NOT NULL,
    domain TEXT NOT NULL,
    entanglement REAL,
    tunneling REAL,
    noise REAL,
    load_val REAL,
    time_val REAL,
    coherence_result REAL NOT NULL,
    computed_at TEXT NOT NULL,
    metadata TEXT
);

CREATE INDEX IF NOT EXISTS idx_ext_formula_domain ON nate_ext_formula_results(domain, computed_at);
CREATE INDEX IF NOT EXISTS idx_ext_formula_name ON nate_ext_formula_results(formula_name);

-- ── Webhook Dispatch Log ──
CREATE TABLE IF NOT EXISTS nate_ext_webhook_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    webhook_name TEXT NOT NULL,
    target_url TEXT NOT NULL,
    status_code INTEGER,
    response_body TEXT,
    fired_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ext_webhook_name ON nate_ext_webhook_log(webhook_name, fired_at);

-- Migration 413: Data Tombstones for Rolling Retention (Slice 1)
-- Additive-only. Supports:
--   • Automated rolling retention (Exhibit L / Section 8.4)
--   • Flutter local-cache sync of server-side deletes (device-history-sync)
--
-- No existing rows are modified; only a new table + indexes are created.

CREATE TABLE IF NOT EXISTS data_tombstones (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    table_name VARCHAR(64) NOT NULL,
    row_id VARCHAR(64) NOT NULL,
    reason VARCHAR(64) NOT NULL DEFAULT 'retention_policy',
    tombstoned_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Client-sync path: "give me my tombstones since <ts>". Composite index on
-- (user_id, tombstoned_at DESC) is the hot path — every Flutter reconnect
-- performs one bounded scan per user.
CREATE INDEX IF NOT EXISTS idx_data_tombstones_user_time
    ON data_tombstones (user_id, tombstoned_at DESC);

-- Admin / auditor path: batch inspection of a particular table's deletes.
CREATE INDEX IF NOT EXISTS idx_data_tombstones_table
    ON data_tombstones (table_name, tombstoned_at DESC);

COMMENT ON TABLE data_tombstones IS
    'Append-only ledger of server-side row deletes. Populated by the '
    'retention enforcer and R2 archive agent. Consumed by Flutter '
    'clients on reconnect (see device-history-sync-on-login.mdc) so '
    'local SQLite/hive caches can drop matching rows.';

COMMENT ON COLUMN data_tombstones.reason IS
    'Why the row was removed. Current values: retention_policy, '
    'r2_archive, admin_purge, user_delete.';

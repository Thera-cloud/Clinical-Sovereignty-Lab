-- QUANTUM-CRYSTAL-ARCH — LN7 fuel gauge snapshots + notification latch (Step 6.3)
CREATE TABLE IF NOT EXISTS ln7_fuel_snapshots (
    snap_date   DATE NOT NULL,
    domain_tag  TEXT NOT NULL,
    trainable   INT  NOT NULL DEFAULT 0,
    total       INT  NOT NULL DEFAULT 0,
    PRIMARY KEY (snap_date, domain_tag)
);

CREATE TABLE IF NOT EXISTS ln7_fuel_notifications (
    domain_tag  TEXT NOT NULL,
    kind        TEXT NOT NULL,  -- approach | crossed | stall
    sent_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    detail      TEXT,
    PRIMARY KEY (domain_tag, kind)
);

COMMENT ON TABLE ln7_fuel_snapshots IS
  'Nightly trainable-row counts per domain for PRE6 ETA (Attempt 6 post-bakeoff Step 6.3)';

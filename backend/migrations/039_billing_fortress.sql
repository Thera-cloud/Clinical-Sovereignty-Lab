-- Migration 039: Billing Fortress (Hive Defense v4.0)
-- Three-Cord webhook verification, trial fingerprinting, atomic usage metering, billing anomaly detection

-- Enhance webhook_events for full idempotency tracking
CREATE TABLE IF NOT EXISTS webhook_events_v2 (
    id              BIGSERIAL PRIMARY KEY,
    event_id        TEXT UNIQUE NOT NULL,
    provider        TEXT NOT NULL DEFAULT 'stripe',
    event_type      TEXT NOT NULL,
    payload_hash    TEXT,
    cord1_passed    BOOLEAN DEFAULT FALSE,
    cord2_passed    BOOLEAN DEFAULT FALSE,
    cord3_passed    BOOLEAN DEFAULT FALSE,
    processing_result TEXT DEFAULT 'pending',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_webhook_events_v2_event_id ON webhook_events_v2 (event_id);
CREATE INDEX IF NOT EXISTS idx_webhook_events_v2_created ON webhook_events_v2 (created_at);

-- Trial fingerprints for abuse prevention
CREATE TABLE IF NOT EXISTS trial_fingerprints (
    id              BIGSERIAL PRIMARY KEY,
    field_type      TEXT NOT NULL,  -- email_hash, phone_hash, device_id_hash, ip_geo_hash, payment_method_hash
    field_hash      TEXT NOT NULL,
    user_id         TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (field_type, field_hash)
);
CREATE INDEX IF NOT EXISTS idx_trial_fp_field ON trial_fingerprints (field_type, field_hash);

-- Atomic usage meters (prevents race conditions)
CREATE TABLE IF NOT EXISTS usage_meters (
    id              BIGSERIAL PRIMARY KEY,
    user_id         TEXT NOT NULL,
    feature         TEXT NOT NULL,
    billing_month   TEXT NOT NULL,  -- YYYY-MM
    current_usage   REAL NOT NULL DEFAULT 0,
    max_limit       REAL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, feature, billing_month)
);
CREATE INDEX IF NOT EXISTS idx_usage_meters_user ON usage_meters (user_id, billing_month);

-- Billing anomaly log
CREATE TABLE IF NOT EXISTS billing_anomalies (
    id              BIGSERIAL PRIMARY KEY,
    rule_name       TEXT NOT NULL,
    description     TEXT,
    event_count     INT,
    threshold       INT,
    alert_level     TEXT NOT NULL DEFAULT 'medium',
    action_taken    TEXT,
    resolved        BOOLEAN DEFAULT FALSE,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_billing_anomalies_detected ON billing_anomalies (detected_at);

-- Commission audit log
CREATE TABLE IF NOT EXISTS commission_audit (
    id              BIGSERIAL PRIMARY KEY,
    session_id      TEXT NOT NULL,
    coach_id        TEXT NOT NULL,
    payment_intent_id TEXT,
    amount_paid     INT NOT NULL,  -- cents
    commission_amount INT NOT NULL,  -- cents
    platform_take   INT NOT NULL,  -- cents
    commission_pct  REAL NOT NULL,
    pack_type       TEXT,
    verified_by     TEXT DEFAULT 'server_side_calculation',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_commission_audit_coach ON commission_audit (coach_id, created_at);

-- Valid price IDs registry (server-side enforcement)
CREATE TABLE IF NOT EXISTS valid_price_registry (
    price_id        TEXT PRIMARY KEY,
    tier            TEXT NOT NULL,
    amount_cents    INT NOT NULL,
    description     TEXT,
    active          BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed valid prices
INSERT INTO valid_price_registry (price_id, tier, amount_cents, description) VALUES
    ('price_inner_chamber_monthly',     'inner_chamber',    4900,   'Inner Chamber Monthly $49'),
    ('price_inner_chamber_founding',    'inner_chamber',    3900,   'Inner Chamber Founding $39'),
    ('price_sovereign_circle_monthly',  'sovereign_circle', 14900,  'Sovereign Circle Monthly $149'),
    ('price_sovereign_circle_founding', 'sovereign_circle', 11900,  'Sovereign Circle Founding $119'),
    ('price_family_addon',              'family_addon',     7500,   'Family Add-on 1st $75'),
    ('price_family_addon_2nd',          'family_addon',     6000,   'Family Add-on 2nd $60'),
    ('price_family_addon_3rd',          'family_addon',     4500,   'Family Add-on 3rd $45'),
    ('price_family_addon_4th',          'family_addon',     3000,   'Family Add-on 4th $30'),
    ('price_session_single',            'session_pack',     17500,  'Single Session $175'),
    ('price_session_4pack',             'session_pack',     60000,  '4-Pack Sessions $600'),
    ('price_session_8pack',             'session_pack',     112000, '8-Pack Sessions $1120')
ON CONFLICT (price_id) DO NOTHING;

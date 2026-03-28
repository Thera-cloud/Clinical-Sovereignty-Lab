-- Sovereign Sanctuary — D1 Hot Transactional Schema
--
-- D1 (SQLite at edge) handles hot reads for:
--   - Live user presence / session state
--   - Coach schedules & availability
--   - Active client rosters (denormalized)
--   - Real-time token balances
--   - Feature/tier gate lookups
--   - Rate limiting counters
--
-- PostgreSQL remains the source of truth. D1 is a read-optimized
-- edge cache that syncs from PG every 30 seconds.

-- ─── Active User Presence ───────────────────────────────────────
-- Who is online right now? Updated on WebSocket connect/disconnect.
CREATE TABLE IF NOT EXISTS user_presence (
    username       TEXT PRIMARY KEY,
    role           TEXT NOT NULL,          -- CLIENT, COACH, ADMIN
    hardware_id    TEXT,
    is_online      INTEGER DEFAULT 0,      -- 1 = connected
    last_seen_at   TEXT,                   -- ISO timestamp
    connected_at   TEXT,
    portal         TEXT,                   -- app, coach, command
    device_type    TEXT                    -- web, ios, android
);

CREATE INDEX IF NOT EXISTS idx_presence_online ON user_presence(is_online) WHERE is_online = 1;
CREATE INDEX IF NOT EXISTS idx_presence_role ON user_presence(role);

-- ─── Coach Schedules ────────────────────────────────────────────
-- Upcoming sessions for the next 14 days. Fast read for coach
-- dashboards and client scheduling.
CREATE TABLE IF NOT EXISTS coach_schedules (
    session_id     TEXT PRIMARY KEY,
    coach_id       TEXT NOT NULL,
    client_id      TEXT NOT NULL,
    client_name    TEXT,
    status         TEXT NOT NULL,          -- SCHEDULED, IN_PROGRESS, COMPLETED, CANCELLED
    session_type   TEXT,                   -- STANDARD, MASTER_CONSULTATION, etc.
    scheduled_at   TEXT,                   -- ISO timestamp
    scheduled_start TEXT,
    scheduled_end  TEXT,
    duration_minutes INTEGER DEFAULT 30,
    zoom_link      TEXT,
    payment_status TEXT,
    family_id      TEXT,
    updated_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_sched_coach ON coach_schedules(coach_id, status);
CREATE INDEX IF NOT EXISTS idx_sched_client ON coach_schedules(client_id);
CREATE INDEX IF NOT EXISTS idx_sched_time ON coach_schedules(scheduled_at);

-- ─── Active Client Roster ───────────────────────────────────────
-- Denormalized client list per coach for fast dashboard rendering.
-- Replaces the heavy PG query in coach_get_clients.
CREATE TABLE IF NOT EXISTS client_roster (
    username       TEXT PRIMARY KEY,
    display_name   TEXT,
    coach_id       TEXT NOT NULL,          -- assigned coach hardware_id
    coach_username TEXT,                   -- assigned coach username
    tier           TEXT,                   -- STANDARD, TOP_TIER, TRIAL
    subscription_status TEXT,              -- ACTIVE, TRIAL_ACTIVE
    family_id      TEXT,
    company_id     TEXT,
    company_name   TEXT,
    group_id       TEXT,
    email          TEXT,
    phone          TEXT,
    last_session_at TEXT,
    token_balance  INTEGER DEFAULT 0,
    is_active      INTEGER DEFAULT 1,
    updated_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_roster_coach ON client_roster(coach_id);
CREATE INDEX IF NOT EXISTS idx_roster_family ON client_roster(family_id) WHERE family_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_roster_company ON client_roster(company_id) WHERE company_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_roster_group ON client_roster(group_id) WHERE group_id IS NOT NULL;

-- ─── Token Balances ─────────────────────────────────────────────
-- Real-time token balances for fast read/deduct without PG round-trip.
CREATE TABLE IF NOT EXISTS token_balances (
    username       TEXT PRIMARY KEY,
    balance        INTEGER DEFAULT 0,
    usage_today    INTEGER DEFAULT 0,
    usage_month    INTEGER DEFAULT 0,
    tier           TEXT,
    last_deduct_at TEXT,
    updated_at     TEXT
);

-- ─── Tier Gate Cache ────────────────────────────────────────────
-- Fast lookup for feature gating. Replaces per-request PG queries.
CREATE TABLE IF NOT EXISTS tier_gates (
    username       TEXT PRIMARY KEY,
    role           TEXT NOT NULL,
    tier           TEXT NOT NULL,
    subscription_status TEXT NOT NULL,
    dojo_subscriptions TEXT,              -- JSON array of subscribed DOJOs
    has_coaching    INTEGER DEFAULT 0,
    is_founding     INTEGER DEFAULT 0,
    consent_version TEXT,
    updated_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_gates_tier ON tier_gates(tier);
CREATE INDEX IF NOT EXISTS idx_gates_role ON tier_gates(role);

-- ─── Live Session State ─────────────────────────────────────────
-- Active coaching sessions with real-time status.
CREATE TABLE IF NOT EXISTS live_sessions (
    session_id     TEXT PRIMARY KEY,
    coach_id       TEXT NOT NULL,
    client_id      TEXT NOT NULL,
    status         TEXT NOT NULL,          -- WAITING, IN_PROGRESS, PAUSED
    started_at     TEXT,
    zoom_meeting_id TEXT,
    zoom_link      TEXT,
    mood_at_start  TEXT,
    recording_consent INTEGER DEFAULT 0,
    nate_active    INTEGER DEFAULT 0,      -- Little Nate analyzing?
    updated_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_live_coach ON live_sessions(coach_id);
CREATE INDEX IF NOT EXISTS idx_live_status ON live_sessions(status);

-- ─── Coach Availability ─────────────────────────────────────────
-- Pre-computed availability slots for the next 14 days.
CREATE TABLE IF NOT EXISTS coach_availability (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    coach_id       TEXT NOT NULL,
    coach_username TEXT,
    day_of_week    INTEGER,               -- 0=Mon, 6=Sun
    slot_date      TEXT,                  -- YYYY-MM-DD
    start_time     TEXT,                  -- HH:MM
    end_time       TEXT,                  -- HH:MM
    is_available   INTEGER DEFAULT 1,
    is_booked      INTEGER DEFAULT 0,
    session_id     TEXT,                  -- FK if booked
    updated_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_avail_coach ON coach_availability(coach_id, slot_date);
CREATE INDEX IF NOT EXISTS idx_avail_open ON coach_availability(is_available, is_booked) WHERE is_available = 1 AND is_booked = 0;

-- ─── Rate Limits ────────────────────────────────────────────────
-- Per-user rate limiting for API endpoints.
CREATE TABLE IF NOT EXISTS rate_limits (
    key            TEXT PRIMARY KEY,       -- "endpoint:username"
    count          INTEGER DEFAULT 0,
    window_start   TEXT,
    window_seconds INTEGER DEFAULT 60
);

-- ─── Sync Watermarks ────────────────────────────────────────────
-- Track what has been synced from PostgreSQL.
CREATE TABLE IF NOT EXISTS d1_sync_watermarks (
    table_name     TEXT PRIMARY KEY,
    last_synced_at TEXT,
    rows_synced    INTEGER DEFAULT 0,
    updated_at     TEXT
);

-- ═══════════════════════════════════════════════════════════════
-- Phase 2 Expansion Tables (D1 Replication System Build)
-- ═══════════════════════════════════════════════════════════════

-- ─── Crystal Metadata (Edge) ──────────────────────────────────
-- Active crystal IDs + confidence for edge filtering before embedding.
-- Summon worker checks here to skip superseded/low-confidence crystals.
CREATE TABLE IF NOT EXISTS crystal_metadata (
    crystal_id     TEXT PRIMARY KEY,
    domain         TEXT NOT NULL,
    confidence     REAL DEFAULT 0.5,
    scope          TEXT DEFAULT 'global',
    superseded_by  TEXT,
    content_hash   TEXT,
    last_recalled_at TEXT,
    recall_count   INTEGER DEFAULT 0,
    updated_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_crystal_domain ON crystal_metadata(domain);
CREATE INDEX IF NOT EXISTS idx_crystal_confidence ON crystal_metadata(confidence) WHERE confidence >= 0.5;

-- ─── Trust Audit Status (Edge) ────────────────────────────────
-- Latest trust enforcer result for edge health awareness.
-- Cron worker reads this to include trust posture in health sweeps.
CREATE TABLE IF NOT EXISTS trust_audit_status (
    id             INTEGER PRIMARY KEY DEFAULT 1,
    total_checks   INTEGER DEFAULT 0,
    trusted_count  INTEGER DEFAULT 0,
    score_pct      REAL DEFAULT 0.0,
    color          TEXT DEFAULT 'UNKNOWN',
    actions_count  INTEGER DEFAULT 0,
    preflight_pass INTEGER DEFAULT 0,
    preflight_total INTEGER DEFAULT 0,
    timestamp      TEXT NOT NULL
);

-- ─── Social Dashboard Cache (Edge) ────────────────────────────
-- Last 7 days of post analytics aggregated for edge dashboard reads.
CREATE TABLE IF NOT EXISTS social_dashboard_cache (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    platform       TEXT NOT NULL,
    post_id        TEXT,
    likes          INTEGER DEFAULT 0,
    reposts        INTEGER DEFAULT 0,
    comments       INTEGER DEFAULT 0,
    impressions    INTEGER DEFAULT 0,
    captured_date  TEXT NOT NULL,
    updated_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_social_platform ON social_dashboard_cache(platform, captured_date);

-- ─── Device Reputation (Edge) ─────────────────────────────────
-- Per-device trust scores for BLE/NFC mesh and auth-edge checks.
CREATE TABLE IF NOT EXISTS device_reputation_edge (
    device_id      TEXT PRIMARY KEY,
    trust_score    REAL DEFAULT 1.0,
    quarantined    INTEGER DEFAULT 0,
    interaction_count INTEGER DEFAULT 0,
    last_seen_at   TEXT,
    flags          TEXT,
    updated_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_device_quarantined ON device_reputation_edge(quarantined) WHERE quarantined = 1;

-- ─── Compliance Rules (Edge) ──────────────────────────────────
-- Per-jurisdiction compliance rules for edge gating.
CREATE TABLE IF NOT EXISTS compliance_rules_edge (
    jurisdiction   TEXT PRIMARY KEY,
    baa_required   INTEGER DEFAULT 0,
    crisis_path_required INTEGER DEFAULT 1,
    data_retention_days INTEGER DEFAULT 365,
    mandatory_reporting INTEGER DEFAULT 1,
    hipaa_covered  INTEGER DEFAULT 0,
    rules_json     TEXT,
    updated_at     TEXT
);

-- QUANTUM-CRYSTAL-ARCH: Agentic Roadmap Phase 0 — proactive touch outcome view + adaptation shadow
-- Touch log table must exist before the view (commitments table lands in 238).

CREATE TABLE IF NOT EXISTS nate_proactive_touches (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         VARCHAR(64) NOT NULL,
    commitment_id   UUID,
    source_agent    VARCHAR(32) NOT NULL,
    touch_type      VARCHAR(32) NOT NULL DEFAULT 'proactive',
    channel         VARCHAR(10) NOT NULL DEFAULT 'in_app'
        CHECK (channel IN ('sms', 'email', 'in_app', 'websocket')),
    content         TEXT,
    status          VARCHAR(24) NOT NULL DEFAULT 'sent'
        CHECK (status IN (
            'sent', 'responded', 'ignored', 'snoozed',
            'skipped_consent', 'skipped_safe_silence', 'skipped_si_window',
            'skipped_quiet_hours', 'skipped_budget', 'skipped_sensitive',
            'skipped_trial', 'skipped_paused', 'skipped_gate_error'
        )),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    responded_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_nate_proactive_touches_user_created
    ON nate_proactive_touches (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_nate_proactive_touches_budget
    ON nate_proactive_touches (user_id, status, created_at DESC);

CREATE OR REPLACE VIEW proactive_touch_outcome_view AS
WITH touch_events AS (
    SELECT
        t.id,
        t.user_id AS touch_identifier,
        t.source_agent,
        t.touch_type,
        t.channel,
        t.status,
        t.created_at AS sent_at,
        t.responded_at,
        u.username,
        u.id AS user_uuid
    FROM nate_proactive_touches t
    LEFT JOIN users u
        ON u.username = t.user_id
        OR u.hardware_id = t.user_id
        OR u.id::text = t.user_id
    WHERE t.status IN ('sent', 'responded', 'ignored', 'snoozed')
)
SELECT
    te.id AS touch_id,
    te.username,
    te.user_uuid,
    te.touch_identifier,
    te.source_agent,
    te.touch_type,
    te.channel,
    te.status AS raw_status,
    te.sent_at,
    te.responded_at,
    CASE
        WHEN te.responded_at IS NOT NULL THEN 'responded'
        WHEN te.status = 'snoozed' THEN 'snoozed'
        WHEN te.status = 'ignored' THEN 'ignored'
        WHEN te.status = 'sent'
             AND te.sent_at < NOW() - INTERVAL '48 hours' THEN 'ignored'
        ELSE 'pending'
    END AS outcome_class
FROM touch_events te;

COMMENT ON VIEW proactive_touch_outcome_view IS
    'Agentic Phase 0 — classifies proactive touches as responded/snoozed/ignored '
    '(48h attribution window). Requires nate_proactive_touches (migration 238).';

CREATE TABLE IF NOT EXISTS proactive_touch_adaptation_shadow (
    id              BIGSERIAL PRIMARY KEY,
    user_id         VARCHAR(64) NOT NULL,
    source          VARCHAR(32) NOT NULL,
    signal_type     VARCHAR(64) NOT NULL,
    proposed_change JSONB NOT NULL DEFAULT '{}'::jsonb,
    sample_size     INTEGER NOT NULL DEFAULT 0,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reasoning       TEXT
);

CREATE INDEX IF NOT EXISTS idx_touch_adapt_shadow_user_source
    ON proactive_touch_adaptation_shadow (user_id, source, computed_at DESC);
CREATE INDEX IF NOT EXISTS idx_touch_adapt_shadow_computed
    ON proactive_touch_adaptation_shadow (computed_at DESC);

COMMENT ON TABLE proactive_touch_adaptation_shadow IS
    'Agentic Phase 0 — append-only assertiveness proposals for proactive touch '
    'cadence. Never auto-applied; restraint track writes profile_data directly.';

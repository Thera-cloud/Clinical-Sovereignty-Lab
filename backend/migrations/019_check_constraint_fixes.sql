-- =============================================================================
-- Migration 019: Fix CHECK Constraint Mismatches
-- =============================================================================
-- Expands CHECK constraints to match values used by Python code.
-- Also standardizes subscription status values.
-- =============================================================================

-- ─── 1. Expand audit_log.action_type CHECK ──────────────────────────────────
-- Add: DEADMAN_ALERT, TRIAL_REMINDER_SENT, COACHING_REMINDER_SENT, SYSTEM
-- Must drop the immutability trigger temporarily to alter the table.

DROP TRIGGER IF EXISTS audit_log_immutable ON audit_log;

ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS audit_log_action_type_check;
ALTER TABLE audit_log ADD CONSTRAINT audit_log_action_type_check CHECK (
    action_type IN (
        'ACCESS', 'CREATE', 'MODIFY', 'DELETE', 'SECURITY',
        'LOGIN', 'LOGOUT', 'APPROVE', 'REJECT', 'EXPORT',
        'DEADMAN_ALERT', 'TRIAL_REMINDER_SENT', 'COACHING_REMINDER_SENT',
        'SYSTEM'
    )
);

-- Re-create the immutability trigger
CREATE OR REPLACE FUNCTION prevent_audit_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Audit log is immutable. No updates or deletes allowed.';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_log_immutable
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION prevent_audit_modification();

-- ─── 2. Expand users.tier CHECK ─────────────────────────────────────────────
-- Add: TOP_TIER (used by stripe_integration.py)

ALTER TABLE users DROP CONSTRAINT IF EXISTS users_tier_check;
ALTER TABLE users ADD CONSTRAINT users_tier_check CHECK (
    tier IN ('MASTER', 'SUPERVISOR', 'TOP', 'TOP_TIER', 'STANDARD', 'TRIAL', 'DEPENDENT')
);

-- ─── 3. Expand users.subscription_status CHECK ──────────────────────────────
-- Add: PENDING_INVITE, NONE, GRACE_PERIOD

ALTER TABLE users DROP CONSTRAINT IF EXISTS users_subscription_status_check;
ALTER TABLE users ADD CONSTRAINT users_subscription_status_check CHECK (
    subscription_status IN (
        'ACTIVE', 'TRIAL_ACTIVE', 'PENDING_VERIFICATION',
        'FAMILY_PLAN_ACTIVE', 'SUSPENDED', 'CANCELLED',
        'PENDING_INVITE', 'NONE', 'GRACE_PERIOD'
    )
);

-- ─── 4. Expand crisis_watchlist.severity CHECK ──────────────────────────────
-- Add: MEDIUM (used by stripe_integration.py payment failure handler)

ALTER TABLE crisis_watchlist DROP CONSTRAINT IF EXISTS crisis_watchlist_severity_check;
ALTER TABLE crisis_watchlist ADD CONSTRAINT crisis_watchlist_severity_check CHECK (
    severity IN ('CRITICAL', 'WARNING', 'MONITORING', 'MEDIUM')
);

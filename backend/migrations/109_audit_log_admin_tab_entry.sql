-- Add ADMIN_TAB_ENTRY to audit_log.action_type for YubiKey-gated tab activity logging.
-- Used by Sovereign Command Recent Activity live ticker and Activate Defense flow.

BEGIN;

DROP TRIGGER IF EXISTS audit_log_immutable ON audit_log;

ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS audit_log_action_type_check;
ALTER TABLE audit_log ADD CONSTRAINT audit_log_action_type_check CHECK (
    action_type IN (
        'ACCESS', 'CREATE', 'MODIFY', 'DELETE', 'SECURITY',
        'LOGIN', 'LOGOUT', 'APPROVE', 'REJECT', 'EXPORT',
        'DEADMAN_ALERT', 'TRIAL_REMINDER_SENT', 'COACHING_REMINDER_SENT',
        'SYSTEM', 'ADMIN_TAB_ENTRY'
    )
);

CREATE TRIGGER audit_log_immutable
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION prevent_audit_modification();

COMMIT;

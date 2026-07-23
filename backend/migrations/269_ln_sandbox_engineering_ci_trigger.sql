-- QUANTUM-CRYSTAL-ARCH: allow Engineering CI DOJO session trigger_reason
-- Live CI used trigger_reason='engineering_ci' which failed CHECK and fell back to fixtures.

ALTER TABLE ln_sandbox_sessions
    DROP CONSTRAINT IF EXISTS ln_sandbox_sessions_trigger_reason_check;

ALTER TABLE ln_sandbox_sessions
    ADD CONSTRAINT ln_sandbox_sessions_trigger_reason_check
    CHECK (trigger_reason IN (
        'scheduled',
        'idle_window',
        'manual',
        'ci_fixture',
        'engineering_ci'
    ));

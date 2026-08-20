-- Migration 412: Voice Biometrics Opt-Out (IL BIPA §15(b) / BAA §6.3 disable control)
-- Additive-only. Default false preserves existing behavior for all users.
-- Slice 0 of the Bee HIV+ privacy plan.

ALTER TABLE users ADD COLUMN IF NOT EXISTS biometrics_disabled BOOLEAN NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_users_biometrics_disabled
    ON users (biometrics_disabled)
    WHERE biometrics_disabled = true;

CREATE TABLE IF NOT EXISTS biometrics_opt_out_log (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(255) NOT NULL,
    action VARCHAR(32) NOT NULL,
    actor VARCHAR(255) NOT NULL,
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_biometrics_opt_out_log_username
    ON biometrics_opt_out_log (username, created_at DESC);

COMMENT ON COLUMN users.biometrics_disabled IS
    'Voice biometric extraction opt-out per IL BIPA §15(b) and BAA §6.3. When true, voice-derived features (pitch, energy, stress, cadence) are not extracted or stored for this user.';

COMMENT ON TABLE biometrics_opt_out_log IS
    'Append-only audit log of biometrics opt-out toggles. Required by BAA §6.3 for compliance evidence.';

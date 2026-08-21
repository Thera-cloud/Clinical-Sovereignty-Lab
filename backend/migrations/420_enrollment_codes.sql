-- 420_enrollment_codes.sql
-- Slice: cohort enrollment (Bee HIV+ and future cohorts)
-- Additive only: adds two tables, no ALTER on existing tables.
--
-- Purpose
-- -------
-- Give admins a way to enroll users into privacy-tightened cohorts without
-- direct SQL. A code is minted for a specific program_id (e.g. "bee_hiv_plus"),
-- shared out-of-band, and the user redeems via POST /api/enrollment/redeem.
-- Redemption sets users.program_id which downstream policies (cohort-scoped
-- retention, cohort-aware MFA window, crystal program isolation trigger from
-- migration 414) already consume.
--
-- Design notes
-- ------------
-- 1. Codes are opaque strings; the API layer enforces format/length. We store
--    the code verbatim (no hash) because it must be human-shareable and the
--    threat model does not include a compromised DB dumping cleartext codes
--    being worse than direct users.program_id manipulation.
-- 2. max_uses NULL = unlimited (typical for a program-wide launch code);
--    max_uses N = capped (typical for individual invites).
-- 3. Redemption uniqueness is enforced at (code_id, user_id) so retries by
--    the same user are idempotent from the DB's perspective; the API layer
--    returns 200 for the first attempt and 409 for subsequent attempts.
-- 4. Foreign key on users(id) uses ON DELETE CASCADE so purging a user also
--    purges their redemption audit rows (aligns with HIPAA right-to-delete
--    once tombstoning is complete).
-- 5. No trigger. users.program_id is set at redemption time by the endpoint
--    in a single transaction with the redemption insert.

BEGIN;

CREATE TABLE IF NOT EXISTS enrollment_codes (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    code          TEXT         NOT NULL UNIQUE,
    program_id    TEXT         NOT NULL,
    max_uses      INTEGER      NULL,
    uses          INTEGER      NOT NULL DEFAULT 0,
    expires_at    TIMESTAMPTZ  NULL,
    revoked_at    TIMESTAMPTZ  NULL,
    created_by    TEXT         NOT NULL,
    notes         TEXT         NULL,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT enrollment_codes_max_uses_positive
        CHECK (max_uses IS NULL OR max_uses > 0),
    CONSTRAINT enrollment_codes_uses_nonneg
        CHECK (uses >= 0)
);

CREATE INDEX IF NOT EXISTS idx_enrollment_codes_program_id
    ON enrollment_codes (program_id);
CREATE INDEX IF NOT EXISTS idx_enrollment_codes_active
    ON enrollment_codes (revoked_at)
    WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS enrollment_redemptions (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    code_id      UUID         NOT NULL REFERENCES enrollment_codes(id) ON DELETE CASCADE,
    user_id      UUID         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    username     TEXT         NOT NULL,
    program_id   TEXT         NOT NULL,
    redeemed_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    source_ip    INET         NULL,
    user_agent   TEXT         NULL,
    CONSTRAINT enrollment_redemptions_unique
        UNIQUE (code_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_enrollment_redemptions_user_time
    ON enrollment_redemptions (user_id, redeemed_at DESC);
CREATE INDEX IF NOT EXISTS idx_enrollment_redemptions_program
    ON enrollment_redemptions (program_id, redeemed_at DESC);

COMMIT;

-- Migration 082: School Discount Codes
-- Supports FAFSA (6-digit), CEEB/CollegeBoard (6-digit), CSS Profile (4-digit)
-- Verification via ID.me or National Student Clearinghouse (NSC)
-- All fees charged to student account holder

CREATE TABLE IF NOT EXISTS school_discount_codes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code            VARCHAR(10) NOT NULL,
    code_type       VARCHAR(20) NOT NULL CHECK (code_type IN ('FAFSA', 'CEEB', 'CSS_PROFILE')),
    institution_name VARCHAR(255) NOT NULL,
    discount_pct    INTEGER NOT NULL DEFAULT 20 CHECK (discount_pct BETWEEN 1 AND 100),
    status          VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'expired')),
    max_enrollments INTEGER,
    created_by      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (code, code_type)
);

CREATE TABLE IF NOT EXISTS student_verifications (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id),
    school_code_id      UUID NOT NULL REFERENCES school_discount_codes(id),
    student_full_name   VARCHAR(255) NOT NULL,
    date_of_birth       DATE NOT NULL,
    institution_name    VARCHAR(255) NOT NULL,
    attendance_start    DATE NOT NULL,
    attendance_end      DATE,
    verification_method VARCHAR(20) NOT NULL CHECK (verification_method IN ('ID_ME', 'NSC')),
    verification_status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (verification_status IN ('pending', 'verified', 'rejected', 'expired')),
    verification_id     TEXT,
    verified_at         TIMESTAMPTZ,
    expires_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, school_code_id)
);

CREATE INDEX IF NOT EXISTS idx_school_codes_code ON school_discount_codes(code, code_type);
CREATE INDEX IF NOT EXISTS idx_school_codes_status ON school_discount_codes(status);
CREATE INDEX IF NOT EXISTS idx_student_verif_user ON student_verifications(user_id);
CREATE INDEX IF NOT EXISTS idx_student_verif_status ON student_verifications(verification_status);

-- Link users.school_code_id FK (column already exists on users table)
-- Only add constraint if not already present
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_users_school_code'
    ) THEN
        ALTER TABLE users ADD CONSTRAINT fk_users_school_code
            FOREIGN KEY (school_code_id) REFERENCES school_discount_codes(id);
    END IF;
END $$;

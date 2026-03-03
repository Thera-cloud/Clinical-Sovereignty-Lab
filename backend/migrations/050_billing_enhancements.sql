-- ============================================================================
-- Migration 050: Billing Enhancements
-- Scholarship Funds, School Codes, Corporate Sponsors, Promotional Specials
-- ============================================================================

-- ─── Scholarship Funds ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS scholarship_funds (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sponsor_user_id     UUID REFERENCES users(id) ON DELETE SET NULL,
    fund_name           VARCHAR(200) NOT NULL,
    balance_cents       INTEGER NOT NULL DEFAULT 0,
    total_deposited     INTEGER NOT NULL DEFAULT 0,
    total_disbursed     INTEGER NOT NULL DEFAULT 0,
    active              BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scholarship_funds_sponsor
    ON scholarship_funds(sponsor_user_id);

-- ─── Scholarship Allocations ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS scholarship_allocations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fund_id             UUID NOT NULL REFERENCES scholarship_funds(id) ON DELETE CASCADE,
    beneficiary_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    monthly_limit_cents INTEGER,
    used_this_month     INTEGER NOT NULL DEFAULT 0,
    month_reset_at      TIMESTAMPTZ NOT NULL DEFAULT date_trunc('month', NOW()) + INTERVAL '1 month',
    active              BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scholarship_alloc_fund
    ON scholarship_allocations(fund_id);
CREATE INDEX IF NOT EXISTS idx_scholarship_alloc_beneficiary
    ON scholarship_allocations(beneficiary_user_id);

-- ─── Scholarship Transactions ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS scholarship_transactions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fund_id             UUID NOT NULL REFERENCES scholarship_funds(id) ON DELETE CASCADE,
    allocation_id       UUID REFERENCES scholarship_allocations(id) ON DELETE SET NULL,
    amount_cents        INTEGER NOT NULL,
    txn_type            VARCHAR(20) NOT NULL,  -- deposit | withdrawal | refund
    description         TEXT,
    stripe_charge_id    VARCHAR(255),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scholarship_txn_fund
    ON scholarship_transactions(fund_id);

-- ─── School Codes (Student Discounts) ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS school_codes (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_name         VARCHAR(200) NOT NULL,
    school_code         VARCHAR(40) NOT NULL UNIQUE,
    discount_percent    INTEGER NOT NULL DEFAULT 10,
    verification_required BOOLEAN NOT NULL DEFAULT FALSE,
    max_students        INTEGER,
    current_students    INTEGER NOT NULL DEFAULT 0,
    active              BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_school_codes_code
    ON school_codes(school_code);

-- ─── Corporate Sponsors ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS corporate_sponsors (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_name        VARCHAR(200) NOT NULL,
    sponsor_code        VARCHAR(40) NOT NULL UNIQUE,
    discount_type       VARCHAR(20) NOT NULL DEFAULT 'percent',  -- percent | amount | full
    discount_value      INTEGER NOT NULL DEFAULT 0,
    pays_full           BOOLEAN NOT NULL DEFAULT FALSE,
    max_employees       INTEGER,
    current_employees   INTEGER NOT NULL DEFAULT 0,
    billing_contact_email VARCHAR(255),
    stripe_customer_id  VARCHAR(255),
    active              BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_corporate_sponsors_code
    ON corporate_sponsors(sponsor_code);

-- ─── Corporate Enrollments ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS corporate_enrollments (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sponsor_id          UUID NOT NULL REFERENCES corporate_sponsors(id) ON DELETE CASCADE,
    user_id             UUID REFERENCES users(id) ON DELETE SET NULL,
    enrolled_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    verified            BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_corporate_enroll_sponsor
    ON corporate_enrollments(sponsor_id);
CREATE INDEX IF NOT EXISTS idx_corporate_enroll_user
    ON corporate_enrollments(user_id);

-- ─── Promotional Specials ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS promotional_specials (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                VARCHAR(200) NOT NULL,
    discount_type       VARCHAR(20) NOT NULL DEFAULT 'percent',  -- percent | amount
    discount_value      INTEGER NOT NULL DEFAULT 0,
    applicable_tiers    TEXT[] DEFAULT '{}',
    starts_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ends_at             TIMESTAMPTZ NOT NULL,
    max_redemptions     INTEGER,
    current_redemptions INTEGER NOT NULL DEFAULT 0,
    promo_code          VARCHAR(40),
    stripe_coupon_id    VARCHAR(255),
    created_by          UUID REFERENCES users(id) ON DELETE SET NULL,
    active              BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_promo_specials_active
    ON promotional_specials(active, starts_at, ends_at);
CREATE INDEX IF NOT EXISTS idx_promo_specials_code
    ON promotional_specials(promo_code) WHERE promo_code IS NOT NULL;

-- ─── User columns for school/corporate linkage ─────────────────────────────
ALTER TABLE users ADD COLUMN IF NOT EXISTS school_code_id UUID REFERENCES school_codes(id) ON DELETE SET NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS student_verified BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS corporate_enrollment_id UUID REFERENCES corporate_enrollments(id) ON DELETE SET NULL;

-- Migration 085: Corporate Command — CORP_ADMIN role + company_id column
-- Enables scoped admin portal for corporate sponsors to manage their employees.

-- Widen role CHECK to include CORP_ADMIN
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE users ADD CONSTRAINT users_role_check
    CHECK (role IN ('CLIENT', 'COACH', 'ADMIN', 'RESEARCHER', 'CORP_ADMIN'));

-- Add company_id as a real indexed column (currently only in profile_data JSONB)
ALTER TABLE users ADD COLUMN IF NOT EXISTS company_id UUID REFERENCES corporate_sponsors(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_users_company_id ON users(company_id);

-- Add configurable permissions per corporate sponsor
ALTER TABLE corporate_sponsors ADD COLUMN IF NOT EXISTS
    corp_admin_permissions JSONB DEFAULT '{"bulk_import":true,"roster":true,"usage_dashboard":true,"coach_assign":true,"billing":true,"password_reset":true}'::jsonb;

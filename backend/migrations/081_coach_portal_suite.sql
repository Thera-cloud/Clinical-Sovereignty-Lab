-- Migration 081: Coach Portal Enhancement Suite
-- Covers: Phase 2 (FOLDER), Phase 3 (Forms), Phase 3B (F-Codes),
--         Phase 6 (Payment), Phase 7 (Notifications), Phase 8 (Schedule),
--         Phase 9 (Sign-Up Codes)

-- ============================================================
-- Phase 2: FOLDER Tab
-- ============================================================
CREATE TABLE IF NOT EXISTS coach_folders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coach_id TEXT NOT NULL,
    folder_type TEXT NOT NULL CHECK (folder_type IN ('personal','client','family','group','company')),
    parent_id UUID REFERENCES coach_folders(id) ON DELETE CASCADE,
    entity_id TEXT,
    entity_name TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_coach_folders_coach ON coach_folders(coach_id);
CREATE INDEX IF NOT EXISTS idx_coach_folders_entity ON coach_folders(entity_id);

CREATE TABLE IF NOT EXISTS coach_folder_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    folder_id UUID NOT NULL REFERENCES coach_folders(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    file_type TEXT,
    azure_blob_url TEXT,
    file_size_bytes BIGINT DEFAULT 0,
    uploaded_by TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_coach_folder_files_folder ON coach_folder_files(folder_id);

-- ============================================================
-- Phase 3: Form Templates
-- ============================================================
CREATE TABLE IF NOT EXISTS coach_form_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coach_id TEXT,
    title TEXT NOT NULL,
    description TEXT,
    form_schema JSONB NOT NULL DEFAULT '{}',
    form_type TEXT DEFAULT 'custom' CHECK (form_type IN ('system','custom','ai_generated')),
    created_by_ai BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_coach_form_templates_coach ON coach_form_templates(coach_id);

CREATE TABLE IF NOT EXISTS form_submissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id UUID REFERENCES coach_form_templates(id),
    client_id TEXT NOT NULL,
    coach_id TEXT NOT NULL,
    submitted_data JSONB DEFAULT '{}',
    status TEXT DEFAULT 'submitted' CHECK (status IN ('submitted','reviewed','archived')),
    submitted_at TIMESTAMPTZ DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_form_submissions_client ON form_submissions(client_id);

-- ============================================================
-- Phase 3B: F-Code Engine
-- ============================================================
CREATE TABLE IF NOT EXISTS fcode_reference (
    code TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    category TEXT,
    common_symptoms TEXT[],
    icd_chapter TEXT DEFAULT 'F'
);

CREATE TABLE IF NOT EXISTS client_fcodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id TEXT NOT NULL,
    coach_id TEXT,
    fcode TEXT NOT NULL,
    fcode_description TEXT,
    assigned_at TIMESTAMPTZ DEFAULT NOW(),
    milestone_window TEXT CHECK (milestone_window IN ('30d','60d','90d','6mo','12mo')),
    source TEXT NOT NULL CHECK (source IN ('coach','nate_suggestion')),
    confidence_score REAL,
    active BOOLEAN DEFAULT TRUE,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_client_fcodes_client ON client_fcodes(client_id);
CREATE INDEX IF NOT EXISTS idx_client_fcodes_source ON client_fcodes(source);

CREATE TABLE IF NOT EXISTS client_insurance (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id TEXT UNIQUE NOT NULL,
    provider_name TEXT,
    policy_number TEXT,
    group_number TEXT,
    subscriber_name TEXT,
    subscriber_dob DATE,
    subscriber_relationship TEXT,
    insurance_phone TEXT,
    claims_address TEXT,
    auth_number TEXT,
    eap_info TEXT,
    secondary_provider TEXT,
    secondary_policy TEXT,
    consent_fcode_submission BOOLEAN DEFAULT FALSE,
    coach_npi TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Seed a small F-code reference set (top 20 most common)
INSERT INTO fcode_reference (code, description, category) VALUES
('F32.0', 'Major depressive disorder, single episode, mild', 'Depressive'),
('F32.1', 'Major depressive disorder, single episode, moderate', 'Depressive'),
('F32.2', 'Major depressive disorder, single episode, severe', 'Depressive'),
('F33.0', 'Major depressive disorder, recurrent, mild', 'Depressive'),
('F33.1', 'Major depressive disorder, recurrent, moderate', 'Depressive'),
('F41.0', 'Panic disorder', 'Anxiety'),
('F41.1', 'Generalized anxiety disorder', 'Anxiety'),
('F41.9', 'Anxiety disorder, unspecified', 'Anxiety'),
('F43.10', 'Post-traumatic stress disorder, unspecified', 'Trauma'),
('F43.11', 'Post-traumatic stress disorder, acute', 'Trauma'),
('F43.12', 'Post-traumatic stress disorder, chronic', 'Trauma'),
('F43.20', 'Adjustment disorder, unspecified', 'Adjustment'),
('F43.21', 'Adjustment disorder with depressed mood', 'Adjustment'),
('F43.22', 'Adjustment disorder with anxiety', 'Adjustment'),
('F43.23', 'Adjustment disorder with mixed anxiety and depressed mood', 'Adjustment'),
('F60.3', 'Borderline personality disorder', 'Personality'),
('F90.0', 'ADHD, predominantly inattentive type', 'Neurodevelopmental'),
('F90.1', 'ADHD, predominantly hyperactive type', 'Neurodevelopmental'),
('F90.2', 'ADHD, combined type', 'Neurodevelopmental'),
('F42.2', 'Mixed obsessional thoughts and acts', 'OCD')
ON CONFLICT (code) DO NOTHING;

-- ============================================================
-- Phase 6: Payment Collection
-- ============================================================
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS payment_status TEXT DEFAULT 'not_required';
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS payment_amount_cents INTEGER;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS stripe_payment_intent_id TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS payment_due_at TIMESTAMPTZ;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS cancellation_deadline TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS session_payment_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL CHECK (event_type IN ('charge_attempt','charge_success','charge_failed','refund','cancellation')),
    amount_cents INTEGER,
    stripe_id TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_session_payment_events_session ON session_payment_events(session_id);

-- ============================================================
-- Phase 7: SMS/Email Session Notifications
-- ============================================================
CREATE TABLE IF NOT EXISTS session_notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    recipient_id TEXT NOT NULL,
    notification_type TEXT NOT NULL CHECK (notification_type IN ('48h_reminder','72h_payment','payment_failed','payment_success','24h_cancel','session_confirmed')),
    channel TEXT NOT NULL CHECK (channel IN ('sms','email','both')),
    sent_at TIMESTAMPTZ DEFAULT NOW(),
    delivery_status TEXT DEFAULT 'sent'
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_session_notif_dedup ON session_notifications(session_id, recipient_id, notification_type, channel);

-- ============================================================
-- Phase 8: Schedule Calendar
-- ============================================================
CREATE TABLE IF NOT EXISTS coach_availability (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coach_id TEXT NOT NULL,
    day_of_week INTEGER CHECK (day_of_week BETWEEN 0 AND 6),
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    recurring BOOLEAN DEFAULT TRUE,
    specific_date DATE,
    calendar_sync_email TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_coach_availability_coach ON coach_availability(coach_id);

-- ============================================================
-- Phase 9: Coach Sign-Up Codes
-- ============================================================
CREATE TABLE IF NOT EXISTS coach_signup_codes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coach_id TEXT NOT NULL,
    code TEXT UNIQUE NOT NULL,
    sharing_pct INTEGER NOT NULL CHECK (sharing_pct BETWEEN 1 AND 30),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','frozen','disabled')),
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    frozen_at TIMESTAMPTZ,
    freeze_ends_at TIMESTAMPTZ,
    max_linked_entities INTEGER,
    monthly_sharing_cap_cents INTEGER
);
CREATE INDEX IF NOT EXISTS idx_coach_signup_codes_coach ON coach_signup_codes(coach_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_coach_signup_codes_code ON coach_signup_codes(code);

CREATE TABLE IF NOT EXISTS signup_code_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code_id UUID NOT NULL REFERENCES coach_signup_codes(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('client','family','group','company')),
    entity_id TEXT NOT NULL,
    linked_at TIMESTAMPTZ DEFAULT NOW(),
    unlinked_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_signup_code_links_active ON signup_code_links(entity_type, entity_id) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_signup_code_links_code ON signup_code_links(code_id);

CREATE TABLE IF NOT EXISTS signup_sharing_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code_id UUID NOT NULL REFERENCES coach_signup_codes(id),
    coach_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('subscription','dependent','dojo')),
    gross_amount_cents INTEGER NOT NULL DEFAULT 0,
    sharing_pct INTEGER NOT NULL,
    shared_amount_cents INTEGER NOT NULL DEFAULT 0,
    billing_period_start DATE NOT NULL,
    billing_period_end DATE NOT NULL,
    stripe_transfer_id TEXT,
    stripe_invoice_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','completed','reversed','failed')),
    source_note TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sharing_ledger_coach ON signup_sharing_ledger(coach_id);
CREATE INDEX IF NOT EXISTS idx_sharing_ledger_period ON signup_sharing_ledger(billing_period_start, billing_period_end);
CREATE INDEX IF NOT EXISTS idx_sharing_ledger_invoice ON signup_sharing_ledger(stripe_invoice_id);

CREATE TABLE IF NOT EXISTS signup_code_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code_id UUID NOT NULL REFERENCES coach_signup_codes(id),
    admin_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('create','adjust_pct','freeze','unfreeze','disable','cap_update','sharing_reversal')),
    old_value TEXT,
    new_value TEXT,
    reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_signup_audit_code ON signup_code_audit_log(code_id);

-- Migration 081: Coach Portal Enhancement Suite
-- Phase 2: FOLDER tab (coach_folders, coach_folder_files)
-- Phase 3B: F-Code engine (client_fcodes, fcode_reference)
-- Phase 6: Payment collection (session_payment_events)
-- Phase 9: Coach Sign-Up Code revenue sharing

BEGIN;

-- ============================================================
-- Phase 2: Coach Folders
-- ============================================================

CREATE TABLE IF NOT EXISTS coach_folders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coach_id TEXT NOT NULL,
    folder_type TEXT NOT NULL CHECK (folder_type IN ('personal', 'client', 'family', 'group', 'company')),
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
    file_type TEXT DEFAULT 'document',
    file_size_bytes BIGINT DEFAULT 0,
    storage_url TEXT,
    uploaded_by TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_coach_folder_files_folder ON coach_folder_files(folder_id);

-- ============================================================
-- Phase 3: Coach Form Templates (table may already exist)
-- ============================================================

CREATE TABLE IF NOT EXISTS coach_form_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coach_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    form_schema JSONB NOT NULL DEFAULT '{}',
    form_type TEXT DEFAULT 'custom',
    is_system_template BOOLEAN DEFAULT FALSE,
    created_by_ai BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_coach_form_templates_coach ON coach_form_templates(coach_id);

-- ============================================================
-- Phase 3B: F-Code Engine
-- ============================================================

CREATE TABLE IF NOT EXISTS fcode_reference (
    code TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    category TEXT,
    common_symptoms TEXT[],
    parent_code TEXT
);

CREATE TABLE IF NOT EXISTS client_fcodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id TEXT NOT NULL,
    coach_id TEXT NOT NULL,
    fcode TEXT NOT NULL REFERENCES fcode_reference(code),
    fcode_description TEXT,
    assigned_at TIMESTAMPTZ DEFAULT NOW(),
    milestone_window TEXT CHECK (milestone_window IN ('30d', '60d', '90d', '6mo', '12mo')),
    source TEXT NOT NULL CHECK (source IN ('coach', 'nate_suggestion')),
    confidence_score REAL,
    active BOOLEAN DEFAULT TRUE,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_client_fcodes_client ON client_fcodes(client_id);
CREATE INDEX IF NOT EXISTS idx_client_fcodes_coach ON client_fcodes(coach_id);
CREATE INDEX IF NOT EXISTS idx_client_fcodes_active ON client_fcodes(active) WHERE active = TRUE;

-- Seed common F-codes (mental/behavioral health F00-F99 subset)
INSERT INTO fcode_reference (code, description, category, common_symptoms) VALUES
    ('F10.10', 'Alcohol use disorder, mild', 'Substance Use', ARRAY['increased tolerance','withdrawal','cravings']),
    ('F10.20', 'Alcohol use disorder, moderate', 'Substance Use', ARRAY['impaired control','social impairment','risky use']),
    ('F10.21', 'Alcohol use disorder, severe, in remission', 'Substance Use', ARRAY['history of severe AUD','maintained recovery']),
    ('F17.210', 'Nicotine dependence, cigarettes, uncomplicated', 'Substance Use', ARRAY['tobacco use','nicotine cravings','withdrawal']),
    ('F20.0', 'Paranoid schizophrenia', 'Schizophrenia Spectrum', ARRAY['delusions','hallucinations','disorganized thinking']),
    ('F31.0', 'Bipolar disorder, current episode hypomanic', 'Bipolar', ARRAY['elevated mood','decreased need for sleep','increased activity']),
    ('F31.10', 'Bipolar disorder, current episode manic without psychotic features, unspecified', 'Bipolar', ARRAY['mania','grandiosity','pressured speech']),
    ('F31.30', 'Bipolar disorder, current episode depressed, mild', 'Bipolar', ARRAY['depressed mood','loss of interest','fatigue']),
    ('F31.9', 'Bipolar disorder, unspecified', 'Bipolar', ARRAY['mood cycling','episodes unclear']),
    ('F32.0', 'Major depressive disorder, single episode, mild', 'Depressive', ARRAY['depressed mood','loss of interest','sleep changes']),
    ('F32.1', 'Major depressive disorder, single episode, moderate', 'Depressive', ARRAY['depressed mood','worthlessness','concentration difficulty']),
    ('F32.2', 'Major depressive disorder, single episode, severe without psychotic features', 'Depressive', ARRAY['severe depression','suicidal ideation','psychomotor changes']),
    ('F32.9', 'Major depressive disorder, single episode, unspecified', 'Depressive', ARRAY['depression NOS']),
    ('F33.0', 'Major depressive disorder, recurrent, mild', 'Depressive', ARRAY['recurrent depression','mild episodes']),
    ('F33.1', 'Major depressive disorder, recurrent, moderate', 'Depressive', ARRAY['recurrent moderate depression']),
    ('F33.2', 'Major depressive disorder, recurrent, severe without psychotic features', 'Depressive', ARRAY['recurrent severe depression']),
    ('F34.1', 'Dysthymic disorder', 'Depressive', ARRAY['persistent low mood','chronic depression','2+ years duration']),
    ('F40.10', 'Social anxiety disorder', 'Anxiety', ARRAY['social fear','avoidance','performance anxiety']),
    ('F40.11', 'Social anxiety disorder, generalized', 'Anxiety', ARRAY['pervasive social fear','avoidance of most social situations']),
    ('F41.0', 'Panic disorder', 'Anxiety', ARRAY['panic attacks','chest pain','fear of dying','palpitations']),
    ('F41.1', 'Generalized anxiety disorder', 'Anxiety', ARRAY['excessive worry','restlessness','muscle tension','sleep disturbance']),
    ('F41.9', 'Anxiety disorder, unspecified', 'Anxiety', ARRAY['anxiety NOS']),
    ('F42.2', 'Mixed obsessional thoughts and acts', 'OCD', ARRAY['obsessions','compulsions','ritualistic behavior']),
    ('F42.9', 'Obsessive-compulsive disorder, unspecified', 'OCD', ARRAY['OCD NOS']),
    ('F43.0', 'Acute stress reaction', 'Trauma/Stress', ARRAY['acute stress','dissociation','re-experiencing']),
    ('F43.10', 'Post-traumatic stress disorder, unspecified', 'Trauma/Stress', ARRAY['flashbacks','nightmares','hypervigilance','avoidance']),
    ('F43.11', 'Post-traumatic stress disorder, acute', 'Trauma/Stress', ARRAY['acute PTSD','< 3 months']),
    ('F43.12', 'Post-traumatic stress disorder, chronic', 'Trauma/Stress', ARRAY['chronic PTSD','> 3 months']),
    ('F43.20', 'Adjustment disorder, unspecified', 'Trauma/Stress', ARRAY['adjustment difficulty','stressor response']),
    ('F43.21', 'Adjustment disorder with depressed mood', 'Trauma/Stress', ARRAY['adjustment depression','situational sadness']),
    ('F43.22', 'Adjustment disorder with anxiety', 'Trauma/Stress', ARRAY['adjustment anxiety','worry about stressor']),
    ('F43.23', 'Adjustment disorder with mixed anxiety and depressed mood', 'Trauma/Stress', ARRAY['mixed adjustment','anxiety and depression']),
    ('F43.25', 'Adjustment disorder with mixed disturbance of emotions and conduct', 'Trauma/Stress', ARRAY['behavioral and emotional disturbance']),
    ('F44.0', 'Dissociative amnesia', 'Dissociative', ARRAY['memory gaps','traumatic amnesia']),
    ('F44.81', 'Dissociative identity disorder', 'Dissociative', ARRAY['identity disruption','amnesia','alter states']),
    ('F45.1', 'Undifferentiated somatoform disorder', 'Somatic', ARRAY['physical complaints','no medical explanation']),
    ('F48.1', 'Depersonalization-derealization syndrome', 'Dissociative', ARRAY['detachment from self','unreality','emotional numbing']),
    ('F50.00', 'Anorexia nervosa, unspecified', 'Eating', ARRAY['restriction','low weight','fear of weight gain']),
    ('F50.01', 'Anorexia nervosa, restricting type', 'Eating', ARRAY['food restriction','excessive exercise']),
    ('F50.02', 'Anorexia nervosa, binge eating/purging type', 'Eating', ARRAY['binge-purge cycles','restriction']),
    ('F50.2', 'Bulimia nervosa', 'Eating', ARRAY['binge eating','purging','compensatory behavior']),
    ('F50.81', 'Binge eating disorder', 'Eating', ARRAY['recurrent binge eating','loss of control','distress']),
    ('F60.0', 'Paranoid personality disorder', 'Personality', ARRAY['distrust','suspicion','guardedness']),
    ('F60.1', 'Schizoid personality disorder', 'Personality', ARRAY['social detachment','restricted affect']),
    ('F60.2', 'Antisocial personality disorder', 'Personality', ARRAY['disregard for rights','deceitfulness','impulsivity']),
    ('F60.3', 'Borderline personality disorder', 'Personality', ARRAY['instability','abandonment fear','impulsivity','self-harm']),
    ('F60.4', 'Histrionic personality disorder', 'Personality', ARRAY['attention-seeking','dramatic behavior','emotional lability']),
    ('F60.5', 'Obsessive-compulsive personality disorder', 'Personality', ARRAY['perfectionism','rigidity','control']),
    ('F60.6', 'Avoidant personality disorder', 'Personality', ARRAY['social inhibition','inadequacy feelings','hypersensitivity to rejection']),
    ('F60.7', 'Dependent personality disorder', 'Personality', ARRAY['submissive behavior','need to be taken care of','separation fear']),
    ('F60.81', 'Narcissistic personality disorder', 'Personality', ARRAY['grandiosity','need for admiration','lack of empathy']),
    ('F63.0', 'Pathological gambling', 'Impulse Control', ARRAY['gambling urges','financial problems','preoccupation']),
    ('F90.0', 'ADHD, predominantly inattentive type', 'ADHD', ARRAY['inattention','disorganization','forgetfulness']),
    ('F90.1', 'ADHD, predominantly hyperactive type', 'ADHD', ARRAY['hyperactivity','impulsivity','restlessness']),
    ('F90.2', 'ADHD, combined type', 'ADHD', ARRAY['inattention','hyperactivity','impulsivity']),
    ('F90.9', 'ADHD, unspecified type', 'ADHD', ARRAY['attention deficit NOS']),
    ('F91.3', 'Oppositional defiant disorder', 'Behavioral', ARRAY['defiance','anger','vindictiveness']),
    ('F93.0', 'Separation anxiety disorder of childhood', 'Childhood Anxiety', ARRAY['separation distress','clinginess','school refusal']),
    ('F94.0', 'Selective mutism', 'Childhood Anxiety', ARRAY['consistent failure to speak in social situations']),
    ('F95.2', 'Tourette syndrome', 'Tic Disorders', ARRAY['motor tics','vocal tics'])
ON CONFLICT (code) DO NOTHING;

-- ============================================================
-- Phase 6: Payment Collection
-- ============================================================

ALTER TABLE coaching_sessions ADD COLUMN IF NOT EXISTS payment_status TEXT DEFAULT 'pending';
ALTER TABLE coaching_sessions ADD COLUMN IF NOT EXISTS payment_amount_cents INTEGER;
ALTER TABLE coaching_sessions ADD COLUMN IF NOT EXISTS stripe_payment_intent_id TEXT;
ALTER TABLE coaching_sessions ADD COLUMN IF NOT EXISTS payment_due_at TIMESTAMPTZ;
ALTER TABLE coaching_sessions ADD COLUMN IF NOT EXISTS cancellation_deadline TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS session_payment_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('charge_attempted', 'charge_succeeded', 'charge_failed', 'refund', 'cancellation', 'reminder_sent')),
    amount_cents INTEGER,
    stripe_payment_intent_id TEXT,
    error_message TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_session_payment_events_session ON session_payment_events(session_id);

CREATE TABLE IF NOT EXISTS session_notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL,
    notification_type TEXT NOT NULL CHECK (notification_type IN ('reminder_48h', 'payment_due_72h', 'payment_failed', 'cancellation', 'confirmation')),
    channel TEXT NOT NULL CHECK (channel IN ('sms', 'email')),
    recipient_id TEXT NOT NULL,
    sent_at TIMESTAMPTZ DEFAULT NOW(),
    status TEXT DEFAULT 'sent',
    UNIQUE (session_id, notification_type, channel, recipient_id)
);

-- ============================================================
-- Phase 8: Coach Availability
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
-- Phase 9: Coach Sign-Up Code Revenue Sharing
-- ============================================================

CREATE TABLE IF NOT EXISTS coach_signup_codes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coach_id TEXT NOT NULL,
    code TEXT NOT NULL UNIQUE,
    sharing_pct INTEGER NOT NULL CHECK (sharing_pct BETWEEN 1 AND 30),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'frozen', 'disabled')),
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
    code_id UUID NOT NULL REFERENCES coach_signup_codes(id),
    entity_type TEXT NOT NULL CHECK (entity_type IN ('client', 'family', 'group', 'company')),
    entity_id TEXT NOT NULL,
    linked_at TIMESTAMPTZ DEFAULT NOW(),
    unlinked_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive'))
);

CREATE INDEX IF NOT EXISTS idx_signup_code_links_code ON signup_code_links(code_id);
CREATE INDEX IF NOT EXISTS idx_signup_code_links_entity ON signup_code_links(entity_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_signup_code_links_active ON signup_code_links(entity_type, entity_id) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS signup_sharing_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code_id UUID NOT NULL REFERENCES coach_signup_codes(id),
    coach_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('subscription', 'dependent', 'dojo')),
    gross_amount_cents INTEGER NOT NULL,
    sharing_pct INTEGER NOT NULL,
    shared_amount_cents INTEGER NOT NULL,
    billing_period_start DATE NOT NULL,
    billing_period_end DATE NOT NULL,
    stripe_transfer_id TEXT,
    stripe_invoice_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'reversed', 'failed')),
    source_note TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_signup_sharing_ledger_coach ON signup_sharing_ledger(coach_id);
CREATE INDEX IF NOT EXISTS idx_signup_sharing_ledger_period ON signup_sharing_ledger(billing_period_start, billing_period_end);

CREATE TABLE IF NOT EXISTS signup_code_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code_id UUID NOT NULL REFERENCES coach_signup_codes(id),
    admin_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('create', 'adjust_pct', 'freeze', 'unfreeze', 'disable', 'cap_update', 'sharing_reversal')),
    old_value TEXT,
    new_value TEXT,
    reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_signup_code_audit_log_code ON signup_code_audit_log(code_id);

COMMIT;

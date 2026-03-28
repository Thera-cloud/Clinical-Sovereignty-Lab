-- Migration: Create Clinical Sovereignty Lab Patient Sovereignty Tables
-- HIPAA-Grade Patient Data Vaults with Audit Trails

BEGIN;

-- Patient Sovereignty Vaults (encrypted metadata, key management)
CREATE TABLE IF NOT EXISTS patient_sovereignty_vaults (
    id BIGSERIAL PRIMARY KEY,
    patient_id UUID NOT NULL UNIQUE,
    encrypted_metadata TEXT NOT NULL,
    key_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    
    CONSTRAINT valid_patient_id CHECK (patient_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')
);

CREATE INDEX idx_patient_sovereignty_vaults_patient_id ON patient_sovereignty_vaults(patient_id);
CREATE INDEX idx_patient_sovereignty_vaults_deleted_at ON patient_sovereignty_vaults(deleted_at);

-- Encrypted Patient Data
CREATE TABLE IF NOT EXISTS patient_sovereignty_data (
    id BIGSERIAL PRIMARY KEY,
    vault_id BIGINT NOT NULL REFERENCES patient_sovereignty_vaults(id) ON DELETE CASCADE,
    category VARCHAR(100) NOT NULL,
    encrypted_data TEXT NOT NULL,
    consent_required BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    accessed_at TIMESTAMPTZ,
    
    CONSTRAINT valid_category CHECK (category IN ('medical_history', 'lab_results', 'genetics', 'prescriptions', 'imaging', 'notes'))
);

CREATE INDEX idx_patient_data_vault_id ON patient_sovereignty_data(vault_id);
CREATE INDEX idx_patient_data_category ON patient_sovereignty_data(category);

-- Immutable Audit Trail (blockchain-style)
CREATE TABLE IF NOT EXISTS patient_sovereignty_audit (
    id BIGSERIAL PRIMARY KEY,
    vault_id BIGINT NOT NULL REFERENCES patient_sovereignty_vaults(id) ON DELETE CASCADE,
    data_id BIGINT REFERENCES patient_sovereignty_data(id) ON DELETE SET NULL,
    action VARCHAR(50) NOT NULL,
    actor VARCHAR(100) NOT NULL,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_vault_id ON patient_sovereignty_audit(vault_id);
CREATE INDEX idx_audit_data_id ON patient_sovereignty_audit(data_id);
CREATE INDEX idx_audit_action ON patient_sovereignty_audit(action);
CREATE INDEX idx_audit_created_at ON patient_sovereignty_audit(created_at);

-- Granular Patient Consents
CREATE TABLE IF NOT EXISTS patient_consents (
    id BIGSERIAL PRIMARY KEY,
    vault_id BIGINT NOT NULL REFERENCES patient_sovereignty_vaults(id) ON DELETE CASCADE,
    data_id BIGINT NOT NULL REFERENCES patient_sovereignty_data(id) ON DELETE CASCADE,
    provider_id UUID NOT NULL,
    scope VARCHAR(100) NOT NULL,
    expires_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    CONSTRAINT consent_not_expired CHECK (
        (expires_at IS NULL OR expires_at > NOW()) AND 
        revoked_at IS NULL
    ),
    
    CONSTRAINT valid_scope CHECK (
        scope IN ('read', 'write', 'share', 'delete')
    )
);

CREATE INDEX idx_consents_vault_id ON patient_consents(vault_id);
CREATE INDEX idx_consents_data_id ON patient_consents(data_id);
CREATE INDEX idx_consents_provider_id ON patient_consents(provider_id);
CREATE INDEX idx_consents_active ON patient_consents(vault_id) 
    WHERE revoked_at IS NULL AND (expires_at IS NULL OR expires_at > NOW());

-- Functions for audit triggers
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_patient_vaults_updated_at 
    BEFORE UPDATE ON patient_sovereignty_vaults 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMIT;

-- Verify tables created
\dt patient_sovereignty_*
\dt patient_consents

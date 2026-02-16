-- Migration 020: PhD Framework Compliance Tables
-- Adds tables and columns required by the theoretical framework audit.
-- Run after all previous migrations.

-- ─── 1. Immutable Approval Decisions Audit Trail (PhD Spec §10.4) ───

CREATE TABLE IF NOT EXISTS approval_decisions_audit (
    audit_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    proposal_id     UUID NOT NULL,
    decision        VARCHAR(20) NOT NULL,          -- APPROVE, REJECT, HOLD, MODIFY
    channel         VARCHAR(50),                    -- email, sms, api, admin_panel
    approver        VARCHAR(255),
    approval_category VARCHAR(20),                  -- OBSERVE, SUGGEST, ACT, CRITICAL
    raw_message     TEXT,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Immutable: no UPDATE or DELETE triggers; append-only
CREATE INDEX IF NOT EXISTS idx_approval_audit_proposal ON approval_decisions_audit(proposal_id);
CREATE INDEX IF NOT EXISTS idx_approval_audit_created ON approval_decisions_audit(created_at);

-- ─── 2. Sovereign Immunity Behavioral Baselines (PhD Spec §8.5) ───

CREATE TABLE IF NOT EXISTS fibre_behavioral_baselines (
    baseline_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fibre_id        UUID NOT NULL,
    metric_name     VARCHAR(100) NOT NULL,         -- msg_rate_per_min, topic_spread, token_usage, conclusion_diversity
    baseline_mean   DOUBLE PRECISION NOT NULL,
    baseline_std    DOUBLE PRECISION NOT NULL DEFAULT 0,
    sample_count    INTEGER NOT NULL DEFAULT 0,
    window_hours    INTEGER NOT NULL DEFAULT 24,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(fibre_id, metric_name)
);

CREATE INDEX IF NOT EXISTS idx_baseline_fibre ON fibre_behavioral_baselines(fibre_id);

-- ─── 3. Enhanced Legacy Vault Consent Columns (PhD Spec §11.3) ───

-- Add granular consent columns if they don't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'legacy_vault_consent' AND column_name = 'data_types'
    ) THEN
        ALTER TABLE legacy_vault_consent ADD COLUMN data_types JSONB DEFAULT NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'legacy_vault_consent' AND column_name = 'is_minor'
    ) THEN
        ALTER TABLE legacy_vault_consent ADD COLUMN is_minor BOOLEAN DEFAULT FALSE;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'legacy_vault_consent' AND column_name = 'guardian_id'
    ) THEN
        ALTER TABLE legacy_vault_consent ADD COLUMN guardian_id UUID DEFAULT NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'legacy_vault_consent' AND column_name = 'sharing_restricted'
    ) THEN
        ALTER TABLE legacy_vault_consent ADD COLUMN sharing_restricted BOOLEAN DEFAULT FALSE;
    END IF;
END$$;

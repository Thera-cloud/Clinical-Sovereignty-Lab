-- Migration 059: Hive Defense Schema Alignment
-- Adds missing columns that worker code expects but were not in original table definitions.
-- All use ADD COLUMN IF NOT EXISTS for idempotency.

-- 1. canary_access_events: worker needs 'processed' flag
ALTER TABLE canary_access_events ADD COLUMN IF NOT EXISTS processed BOOLEAN DEFAULT FALSE;

-- 2. hive_defcon_triggers: evaluator worker expects severity/details/processed/created_at
ALTER TABLE hive_defcon_triggers ADD COLUMN IF NOT EXISTS severity VARCHAR(50) DEFAULT 'info';
ALTER TABLE hive_defcon_triggers ADD COLUMN IF NOT EXISTS details TEXT;
ALTER TABLE hive_defcon_triggers ADD COLUMN IF NOT EXISTS processed BOOLEAN DEFAULT FALSE;
ALTER TABLE hive_defcon_triggers ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ;
ALTER TABLE hive_defcon_triggers ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();

-- 3. hive_fibre_births: birth rate monitor expects entity_id/fibre_type/ring_region/certificate_id/created_at
ALTER TABLE hive_fibre_births ADD COLUMN IF NOT EXISTS entity_id UUID;
ALTER TABLE hive_fibre_births ADD COLUMN IF NOT EXISTS fibre_type VARCHAR(50);
ALTER TABLE hive_fibre_births ADD COLUMN IF NOT EXISTS ring_region VARCHAR(50);
ALTER TABLE hive_fibre_births ADD COLUMN IF NOT EXISTS certificate_id UUID;
ALTER TABLE hive_fibre_births ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();

-- 4. hive_birth_rate_metrics: birth monitor persist expects sweep_number/current_rate/threshold/anomalies_detected/swept_at
ALTER TABLE hive_birth_rate_metrics ADD COLUMN IF NOT EXISTS sweep_number INTEGER DEFAULT 0;
ALTER TABLE hive_birth_rate_metrics ADD COLUMN IF NOT EXISTS current_rate DOUBLE PRECISION DEFAULT 0.0;
ALTER TABLE hive_birth_rate_metrics ADD COLUMN IF NOT EXISTS threshold DOUBLE PRECISION DEFAULT 0.0;
ALTER TABLE hive_birth_rate_metrics ADD COLUMN IF NOT EXISTS anomalies_detected INTEGER DEFAULT 0;
ALTER TABLE hive_birth_rate_metrics ADD COLUMN IF NOT EXISTS swept_at TIMESTAMPTZ DEFAULT NOW();

-- 5. hive_projected_helix_deployments: projection/recursive-learning workers expect additional columns
ALTER TABLE hive_projected_helix_deployments ADD COLUMN IF NOT EXISTS deployment_id UUID;
ALTER TABLE hive_projected_helix_deployments ADD COLUMN IF NOT EXISTS interactions_mirrored INTEGER DEFAULT 0;
ALTER TABLE hive_projected_helix_deployments ADD COLUMN IF NOT EXISTS commands_intercepted INTEGER DEFAULT 0;
ALTER TABLE hive_projected_helix_deployments ADD COLUMN IF NOT EXISTS last_command_at TIMESTAMPTZ;
ALTER TABLE hive_projected_helix_deployments ADD COLUMN IF NOT EXISTS model_version VARCHAR(50);
ALTER TABLE hive_projected_helix_deployments ADD COLUMN IF NOT EXISTS deployed_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE hive_projected_helix_deployments ADD COLUMN IF NOT EXISTS target_profile_id UUID;
ALTER TABLE hive_projected_helix_deployments ADD COLUMN IF NOT EXISTS penetrator_report_id UUID;
ALTER TABLE hive_projected_helix_deployments ADD COLUMN IF NOT EXISTS authorized_by UUID;
UPDATE hive_projected_helix_deployments SET deployment_id = id WHERE deployment_id IS NULL;

-- 6. hive_heartbeats: heartbeat monitor expects last_pulse_at/birth_coherence_hash/monotonic_counter/active
ALTER TABLE hive_heartbeats ADD COLUMN IF NOT EXISTS last_pulse_at TIMESTAMPTZ;
ALTER TABLE hive_heartbeats ADD COLUMN IF NOT EXISTS birth_coherence_hash VARCHAR(128);
ALTER TABLE hive_heartbeats ADD COLUMN IF NOT EXISTS monotonic_counter BIGINT DEFAULT 0;
ALTER TABLE hive_heartbeats ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT TRUE;
UPDATE hive_heartbeats SET last_pulse_at = updated_at WHERE last_pulse_at IS NULL;
UPDATE hive_heartbeats SET birth_coherence_hash = birth_hash WHERE birth_coherence_hash IS NULL;
UPDATE hive_heartbeats SET monotonic_counter = counter WHERE monotonic_counter = 0 AND counter > 0;

-- 7. hive_infinite_mirror_traps: trap monitor expects trap_id/last_interaction_at/interaction_count/status/containment_zone
ALTER TABLE hive_infinite_mirror_traps ADD COLUMN IF NOT EXISTS trap_id UUID;
ALTER TABLE hive_infinite_mirror_traps ADD COLUMN IF NOT EXISTS last_interaction_at TIMESTAMPTZ;
ALTER TABLE hive_infinite_mirror_traps ADD COLUMN IF NOT EXISTS interaction_count INTEGER DEFAULT 0;
ALTER TABLE hive_infinite_mirror_traps ADD COLUMN IF NOT EXISTS status VARCHAR(30) DEFAULT 'active';
ALTER TABLE hive_infinite_mirror_traps ADD COLUMN IF NOT EXISTS containment_zone VARCHAR(100);
UPDATE hive_infinite_mirror_traps SET trap_id = id WHERE trap_id IS NULL;
UPDATE hive_infinite_mirror_traps SET interaction_count = interactions WHERE interaction_count = 0 AND interactions > 0;
UPDATE hive_infinite_mirror_traps SET status = trap_status WHERE status = 'active' AND trap_status IS NOT NULL AND trap_status != 'active';

-- 8. hive_quarantine_records: quarantine evaluator expects duration_minutes
ALTER TABLE hive_quarantine_records ADD COLUMN IF NOT EXISTS duration_minutes INTEGER DEFAULT 0;

-- 9. quakete_energy_ledger: conservation audit worker expects energy_amount/active/entity_id/transaction_type/created_at
ALTER TABLE quakete_energy_ledger ADD COLUMN IF NOT EXISTS energy_amount DOUBLE PRECISION DEFAULT 0.0;
ALTER TABLE quakete_energy_ledger ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT TRUE;
ALTER TABLE quakete_energy_ledger ADD COLUMN IF NOT EXISTS entity_id UUID;
ALTER TABLE quakete_energy_ledger ADD COLUMN IF NOT EXISTS transaction_type VARCHAR(50);
ALTER TABLE quakete_energy_ledger ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();
UPDATE quakete_energy_ledger SET energy_amount = amount WHERE energy_amount = 0.0 AND amount > 0;

-- 10. hive_drift_scores: CDS computation worker expects dimension columns + active/last_updated
ALTER TABLE hive_drift_scores ADD COLUMN IF NOT EXISTS data_access DOUBLE PRECISION DEFAULT 0.0;
ALTER TABLE hive_drift_scores ADD COLUMN IF NOT EXISTS communication DOUBLE PRECISION DEFAULT 0.0;
ALTER TABLE hive_drift_scores ADD COLUMN IF NOT EXISTS coherence DOUBLE PRECISION DEFAULT 0.0;
ALTER TABLE hive_drift_scores ADD COLUMN IF NOT EXISTS trail_emission DOUBLE PRECISION DEFAULT 0.0;
ALTER TABLE hive_drift_scores ADD COLUMN IF NOT EXISTS journal_trajectory DOUBLE PRECISION DEFAULT 0.0;
ALTER TABLE hive_drift_scores ADD COLUMN IF NOT EXISTS timing_pattern DOUBLE PRECISION DEFAULT 0.0;
ALTER TABLE hive_drift_scores ADD COLUMN IF NOT EXISTS combined_magnitude DOUBLE PRECISION DEFAULT 0.0;
ALTER TABLE hive_drift_scores ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT TRUE;
ALTER TABLE hive_drift_scores ADD COLUMN IF NOT EXISTS last_updated TIMESTAMPTZ DEFAULT NOW();
UPDATE hive_drift_scores SET combined_magnitude = combined_mag WHERE combined_magnitude = 0.0 AND combined_mag > 0;
UPDATE hive_drift_scores SET last_updated = updated_at WHERE last_updated IS NULL OR last_updated = updated_at;

-- 11. onboarding_initiations: onboarding worker expects this table
CREATE TABLE IF NOT EXISTS onboarding_initiations (
    id              SERIAL PRIMARY KEY,
    initiation_id   UUID DEFAULT gen_random_uuid(),
    user_id         TEXT NOT NULL,
    name            TEXT,
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    stage           TEXT DEFAULT 'pending',
    assigned_coach_id TEXT,
    metadata        JSONB DEFAULT '{}',
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_onboarding_stage ON onboarding_initiations (stage);

-- 12. hive_canary_metrics: canary check needs canary_id column
ALTER TABLE hive_canary_metrics ADD COLUMN IF NOT EXISTS canary_id TEXT;

-- 13. canary_credentials: worker expects canary_id (join key) and active flag
ALTER TABLE canary_credentials ADD COLUMN IF NOT EXISTS canary_id UUID;
ALTER TABLE canary_credentials ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT TRUE;
UPDATE canary_credentials SET canary_id = id WHERE canary_id IS NULL;

-- 14. hive_heartbeat_metrics: defcon evaluator and heartbeat monitor query swept_at/sweep_number
ALTER TABLE hive_heartbeat_metrics ADD COLUMN IF NOT EXISTS swept_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE hive_heartbeat_metrics ADD COLUMN IF NOT EXISTS sweep_number INTEGER DEFAULT 0;
UPDATE hive_heartbeat_metrics SET swept_at = recorded_at WHERE swept_at IS NULL;

-- 15. quakete_energy_ledger: conservation worker queries ledger_id
ALTER TABLE quakete_energy_ledger ADD COLUMN IF NOT EXISTS ledger_id UUID;
UPDATE quakete_energy_ledger SET ledger_id = id WHERE ledger_id IS NULL;

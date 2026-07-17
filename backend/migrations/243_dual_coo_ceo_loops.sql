-- QUANTUM-CRYSTAL-ARCH: Dual-COO / CEO-Nathan loops
-- 1) Apply log for gated non-clinical confidence writes
-- 2) Patent claim ↔ code map (proposed → CEO/YELLOW approve)

CREATE TABLE IF NOT EXISTS crystal_confidence_apply_log (
    id                BIGSERIAL PRIMARY KEY,
    shadow_id         BIGINT REFERENCES crystal_confidence_shadow(id) ON DELETE SET NULL,
    crystal_id        INTEGER NOT NULL REFERENCES nate_intelligence_crystals(id) ON DELETE CASCADE,
    domain            VARCHAR(50),
    old_confidence    REAL,
    new_confidence    REAL,
    delta             NUMERIC(6,4) NOT NULL,
    sample_size       INTEGER,
    risk_class        VARCHAR(16) NOT NULL DEFAULT 'GREEN',
    applied_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reasoning         TEXT
);

CREATE INDEX IF NOT EXISTS idx_crystal_apply_log_applied
    ON crystal_confidence_apply_log (applied_at DESC);
CREATE INDEX IF NOT EXISTS idx_crystal_apply_log_crystal
    ON crystal_confidence_apply_log (crystal_id, applied_at DESC);

COMMENT ON TABLE crystal_confidence_apply_log IS
    'Dual-COO: GREEN-domain confidence applies from shadow. clinical/defense never auto-applied.';

CREATE TABLE IF NOT EXISTS patent_claim_map (
    id              BIGSERIAL PRIMARY KEY,
    family_id       TEXT NOT NULL,
    claim_ref       TEXT NOT NULL,
    claim_text      TEXT,
    code_path       TEXT NOT NULL DEFAULT '',
    function_name   TEXT NOT NULL DEFAULT '',
    status          VARCHAR(32) NOT NULL DEFAULT 'proposed',
    proposed_by     TEXT DEFAULT 'worker_ant',
    risk_class      VARCHAR(16) NOT NULL DEFAULT 'YELLOW',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at     TIMESTAMPTZ,
    reviewed_by     TEXT,
    UNIQUE (family_id, claim_ref, code_path, function_name)
);

CREATE INDEX IF NOT EXISTS idx_patent_claim_map_status
    ON patent_claim_map (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_patent_claim_map_family
    ON patent_claim_map (family_id);

COMMENT ON TABLE patent_claim_map IS
    'Dual-COO patent guardian: worker-proposed claim↔code tags; CEO batch-approves (YELLOW).';

INSERT INTO patent_claim_map (family_id, claim_ref, claim_text, code_path, function_name, status, proposed_by)
VALUES
    ('provisional_1_qec', 'claim_governance',
     'Nevedal Formula as therapeutic outcome + software governor',
     'backend/app/services/nevedal_engine.py', 'compute_emotional_coherence', 'proposed', 'seed'),
    ('provisional_10_ugf', 'claim_unified_governor',
     'Unified governing function across subsystems',
     'backend/app/services/nevedal_engine.py', 'compute_emotional_coherence', 'proposed', 'seed'),
    ('provisional_10_ugf', 'claim_odpe_routing',
     'ODPE signal routes inference tier',
     'backend/app/services/odpe_engine.py', 'ODPEEngine', 'proposed', 'seed'),
    ('provisional_8_crystal', 'claim_crystal_memory',
     'Intelligence crystals with recall reinforcement',
     'backend/app/websocket/crystal_recall_bridge.py', 'recall_crystals_for_context', 'proposed', 'seed')
ON CONFLICT (family_id, claim_ref, code_path, function_name) DO NOTHING;

-- W13 — Queens SA fence ACL + weld-key flip guard on ln7_feature_flags.
-- QUANTUM-CRYSTAL-ARCH
-- Additive only. Does NOT flip ENABLE_LN7_AUTO_PROMOTE / DUAL_COO_MECHANICAL_PROMOTE.

-- Dedicated Queens role: ledger/task CRUD; feature flags SELECT-only.
DO $$
BEGIN
    CREATE ROLE ln7_queens NOINHERIT;
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

GRANT USAGE ON SCHEMA public TO ln7_queens;

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'ln7_revisions',
        'ln7_coding_outcomes',
        'ln7_pack_candidates',
        'ln7_canary_state',
        'ln7_suppress_patterns',
        'outcome_envelope',
        'growth_claims'
    ]
    LOOP
        IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = t
        ) THEN
            EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE %I TO ln7_queens', t);
        END IF;
    END LOOP;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'ln7_feature_flags'
    ) THEN
        REVOKE ALL ON TABLE ln7_feature_flags FROM ln7_queens;
        GRANT SELECT ON TABLE ln7_feature_flags TO ln7_queens;
    END IF;
END $$;

-- Weld keys require session GUC ln7.allow_weld_flip=on (set only by flip_g2_governance).
CREATE OR REPLACE FUNCTION ln7_feature_flags_weld_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.key IN ('ENABLE_LN7_AUTO_PROMOTE', 'DUAL_COO_MECHANICAL_PROMOTE')
       AND OLD.enabled IS DISTINCT FROM NEW.enabled
       AND current_setting('ln7.allow_weld_flip', true) IS DISTINCT FROM 'on'
    THEN
        RAISE EXCEPTION
            'W13: weld key % flip blocked — set ln7.allow_weld_flip=on (Step 0 / flip_g2 only)',
            NEW.key;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_ln7_feature_flags_weld_guard ON ln7_feature_flags;
CREATE TRIGGER trg_ln7_feature_flags_weld_guard
    BEFORE UPDATE ON ln7_feature_flags
    FOR EACH ROW
    EXECUTE PROCEDURE ln7_feature_flags_weld_guard();

-- Sovereign Studio INV-1 wall — studio_runtime role.
-- Additive. Idempotent. QUANTUM-CRYSTAL-ARCH
-- Role has zero SELECT/INSERT/UPDATE/DELETE on therapeutic tables.

DO $$
BEGIN
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'studio_runtime') THEN
            CREATE ROLE studio_runtime NOLOGIN;
        END IF;
    EXCEPTION WHEN insufficient_privilege THEN
        RAISE NOTICE 'studio_runtime CREATE ROLE skipped (need CREATEROLE)';
    END;
END $$;

DO $$
DECLARE
    t TEXT;
    wall TEXT[] := ARRAY[
        'nate_intelligence_crystals',
        'crystal_recall_log',
        'nevedal_metrics',
        'virtual_eeg_traces',
        'user_safety_codewords',
        'user_trigger_dates',
        'user_polyvictimization_layers',
        'user_legal_status',
        'user_parts_registry',
        'addiction_status_history',
        'cross_addiction_transfer_events',
        'sensitive_bridge_log',
        'sensitive_bridge_enrollment',
        'conversation_history'
    ];
    studio TEXT[] := ARRAY[
        'studio_shows',
        'studio_persona_versions',
        'studio_coach_models',
        'studio_sessions',
        'session_legs',
        'show_callers',
        'caller_topics',
        'consent_records',
        'studio_episodes',
        'studio_compliance_flags',
        'studio_compliance_flag_overrides',
        'studio_show_learning',
        'studio_meter'
    ];
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'studio_runtime') THEN
        RAISE NOTICE 'studio_runtime missing — REVOKE/GRANT skipped';
        RETURN;
    END IF;

    FOREACH t IN ARRAY wall LOOP
        IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = t
        ) THEN
            EXECUTE format('REVOKE ALL ON TABLE %I FROM studio_runtime', t);
        END IF;
    END LOOP;

    FOR t IN
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name LIKE 'pmb_%'
    LOOP
        EXECUTE format('REVOKE ALL ON TABLE %I FROM studio_runtime', t);
    END LOOP;

    FOR t IN
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name LIKE 'sensitive_bridge%'
    LOOP
        EXECUTE format('REVOKE ALL ON TABLE %I FROM studio_runtime', t);
    END LOOP;

    FOREACH t IN ARRAY studio LOOP
        IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = t
        ) THEN
            EXECUTE format('GRANT SELECT, INSERT, UPDATE ON TABLE %I TO studio_runtime', t);
        END IF;
    END LOOP;
END $$;

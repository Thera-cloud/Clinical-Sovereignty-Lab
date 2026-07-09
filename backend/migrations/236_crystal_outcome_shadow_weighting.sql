-- QUANTUM-CRYSTAL-ARCH: WIRE_WHAT_EXISTS Commit 4 (STEP 3 + STEP 4)
--
-- STEP 3: crystal_outcome_view — a READ-ONLY view that attributes a crystal
-- recall event (crystal_recall_log) to the response it fed (conversation_history,
-- via the crystal_ids recorded in metadata by Commit 2 / ENABLE_CRYSTAL_ATTRIBUTION)
-- and to the nearest recorded C_emo outcome (nevedal_metrics), resolving the
-- identity-key mismatch documented in docs/WIRING_AUDIT_REPORT.md:
--   crystal_recall_log.user_id   = hardware_id (TEXT)
--   conversation_history.user_id = username    (TEXT)
--   nevedal_metrics.user_id      = users.id     (UUID)
-- The resolution below mirrors the existing OR-chain in
-- backend/app/services/_identity_resolver.py::resolve_username — it does not
-- invent a new identity strategy.
--
-- STEP 4: crystal_confidence_shadow — an append-only table for PROPOSED
-- confidence deltas computed from crystal_outcome_view. Nothing writes to
-- nate_intelligence_crystals.confidence from this pipeline; that is enforced
-- in code (db_maintenance_agent.py) and verified by
-- backend/tests/test_shadow_weighting_no_update.py, not by this schema.

CREATE OR REPLACE VIEW crystal_outcome_view AS
WITH recall_events AS (
    SELECT
        crl.id           AS recall_log_id,
        crl.crystal_id,
        crl.source,
        crl.session_id   AS recall_session_id,
        crl.call_sid,
        crl.recalled_at,
        crl.user_id      AS recall_identifier,
        u.id             AS user_uuid,
        u.username       AS username
    FROM crystal_recall_log crl
    LEFT JOIN users u
        ON u.username = crl.user_id
        OR u.hardware_id = crl.user_id
        OR u.id::text = crl.user_id
    WHERE crl.crystal_id IS NOT NULL
)
SELECT
    re.recall_log_id,
    re.crystal_id,
    nic.domain            AS crystal_domain,
    nic.confidence        AS crystal_confidence,
    re.source,
    re.recalled_at,
    re.username,
    re.user_uuid,
    ch.id                 AS conversation_history_id,
    ch.created_at         AS response_at,
    ch.session_id         AS response_session_id,
    nm.c_emo,
    nm.recorded_at        AS c_emo_recorded_at
FROM recall_events re
LEFT JOIN nate_intelligence_crystals nic
    ON nic.id = re.crystal_id
LEFT JOIN LATERAL (
    -- Nearest conversation_history row for this username whose metadata
    -- actually lists this crystal_id (written by Commit 2 /
    -- ENABLE_CRYSTAL_ATTRIBUTION), within a tight post-recall window. This is
    -- the "recall -> response" attribution edge; without a matching
    -- crystal_ids entry the recall is treated as unattributed (no row).
    SELECT ch2.id, ch2.created_at, ch2.session_id
    FROM conversation_history ch2
    WHERE ch2.user_id = re.username
      AND ch2.created_at BETWEEN re.recalled_at - INTERVAL '2 minutes'
                              AND re.recalled_at + INTERVAL '10 minutes'
      AND ch2.metadata -> 'crystal_ids' IS NOT NULL
      AND (ch2.metadata -> 'crystal_ids') @> to_jsonb(re.crystal_id)
    ORDER BY ch2.created_at ASC
    LIMIT 1
) ch ON TRUE
LEFT JOIN LATERAL (
    -- Nearest recorded C_emo for this same user around the recall/response
    -- window. nevedal_metrics.user_id is a UUID, so this can only run when
    -- the identity resolution above found a matching users row.
    SELECT nm2.c_emo, nm2.recorded_at
    FROM nevedal_metrics nm2
    WHERE nm2.user_id = re.user_uuid
      AND nm2.recorded_at BETWEEN re.recalled_at - INTERVAL '2 minutes'
                               AND re.recalled_at + INTERVAL '10 minutes'
    ORDER BY ABS(EXTRACT(EPOCH FROM (nm2.recorded_at - re.recalled_at)))
    LIMIT 1
) nm ON re.user_uuid IS NOT NULL;

COMMENT ON VIEW crystal_outcome_view IS
    'WIRE_WHAT_EXISTS Commit 4 STEP 3 — read-only attribution of crystal_recall_log '
    'events to their conversation_history response and nearest nevedal_metrics C_emo. '
    'No underlying table is modified by this view.';

-- STEP 4: shadow confidence-delta proposals. INSERT-only from
-- db_maintenance_agent.py; nothing in this codebase UPDATEs
-- nate_intelligence_crystals.confidence from this pipeline.
CREATE TABLE IF NOT EXISTS crystal_confidence_shadow (
    id                  BIGSERIAL PRIMARY KEY,
    crystal_id           INTEGER NOT NULL REFERENCES nate_intelligence_crystals(id) ON DELETE CASCADE,
    domain                VARCHAR(50),
    current_confidence    REAL,
    proposed_delta        NUMERIC(6,4) NOT NULL,
    sample_size           INTEGER NOT NULL,
    avg_c_emo             NUMERIC(10,6),
    reasoning             TEXT,
    computed_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_crystal_confidence_shadow_crystal
    ON crystal_confidence_shadow (crystal_id, computed_at DESC);
CREATE INDEX IF NOT EXISTS idx_crystal_confidence_shadow_computed
    ON crystal_confidence_shadow (computed_at DESC);

COMMENT ON TABLE crystal_confidence_shadow IS
    'WIRE_WHAT_EXISTS Commit 4 STEP 4 — append-only proposed confidence deltas '
    '(never applied). |proposed_delta| <= 0.02; domain clinical/defense forced to 0. '
    'Populated weekly by DatabaseMaintenanceAgent._shadow_weighting_pass().';

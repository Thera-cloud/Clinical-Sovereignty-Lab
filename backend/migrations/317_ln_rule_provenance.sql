-- Phase H / R6: provenance-independent-user tracking for therapeutic
-- soft-gate rule promotion. Additive only — no existing columns touched.
--
-- Plan requirement: "Export generalization gate: N>=5 provenance-independent
-- users (distinct payment lineage / device fingerprints / coach assignments),
-- not merely N>=5 usernames." ln_rule_audit already records every shadow_fire
-- / fire event for a rule_key+version; this adds a per-event provenance
-- fingerprint so promote_rule() can require >=N DISTINCT fingerprints, not
-- just >=N raw event rows.
--
-- QUANTUM-CRYSTAL-ARCH

ALTER TABLE ln_rule_audit
    ADD COLUMN IF NOT EXISTS provenance_hash TEXT;

CREATE INDEX IF NOT EXISTS idx_ln_rule_audit_provenance
    ON ln_rule_audit (rule_key, action, provenance_hash)
    WHERE provenance_hash IS NOT NULL;

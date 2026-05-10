-- ─────────────────────────────────────────────────────────────────────────
-- Migration 212 — Sensitive Clinical Bridge Auditor trust baseline
-- ─────────────────────────────────────────────────────────────────────────
-- Wires the SensitiveBridgeAuditor (auditor #29) into the trust enforcer
-- fleet baseline. This is Step 1 of Phase 6 Option A: visibility-first.
--
-- Plan v1.3 Phase 6 originally specified 25 checks. Implementation actually
-- delivered 34 (32 inventory slots from _CHECK_ORDER + 1 META + the
-- telemetry-gate check folded inline). All 34 are real, in-process, and
-- ship cheap-first per Phase 5 Note 2.
--
-- Inventory snapshot (sensitive_bridge_auditor.py::_CHECK_ORDER):
--   Tier 1 (sub-ms, in-process)        — 11 slots
--   Tier 2 (10–50 ms, single-shot DB)  —  9 slots
--   Tier 3 (50–100 ms, table scans)    —  5 slots
--   Tier 4 (100s ms, joins + scans)    —  8 slots
--   META   (sub-ms)                    —  1 slot   ← audit_check_ordering_cheap_first
--                                       ────
--                                         34
--
-- 5-location sync (per .cursor/rules/trust-enforcer-architecture.mdc):
--   1. AUDITOR_ACTIVITY_TYPES        — sensitive_bridge_audit_sent      ✅
--   2. AUDITOR_LABELS                — "Sensitive Clinical Bridge"      ✅
--   3. _baseline_key_for() mapping   — sensitive_bridge_check_count     ✅
--   4. trust_baseline row            — this migration                   ✅
--   5. main.py::_service_checks      — sensitive_bridge_auditor         ✅ (pre-existing)
--
-- DEFERRED (Phase 6 Option A scope cut, follow-up ticket):
--   - The plan v1.3 25-check enumeration vs the 34-slot implementation
--     reconciliation. Implementation over-built; the 9-slot delta covers
--     v1.2 parity fold-ins, telemetry-gate, and META. No checks removed.
--   - Cohort + telemetry tier check expansion (Tier 3) once shadow-mode
--     produces 7+ days of detector_telemetry rows.
-- ─────────────────────────────────────────────────────────────────────────

INSERT INTO trust_baseline (parameter_key, parameter_value)
VALUES (
    'sensitive_bridge_check_count',
    '{"expected": 34, "description": "Sensitive Clinical Bridge: Tier1 module self-checks (11) + Tier2 sensitive_log schema/RBAC (9) + Tier3 cohort & telemetry (5) + Tier4 detector flag activation (8) + META audit_check_ordering_cheap_first (1)"}'
)
ON CONFLICT (parameter_key) DO UPDATE SET parameter_value = EXCLUDED.parameter_value;

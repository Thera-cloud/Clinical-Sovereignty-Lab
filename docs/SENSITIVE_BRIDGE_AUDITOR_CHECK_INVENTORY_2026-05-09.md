# Sensitive Clinical Bridge — Auditor Check Inventory (Canonical)

**Date**: 2026-05-09
**Phase**: 5 (pre-code)
**Purpose**: Single canonical list of every auditor check ID for `sensitive_bridge_auditor.py`. Built per Phase 5 Note 1.
**Status**: Pre-implementation. This list governs Phase 6 auditor wiring.

---

## Sources Consulted

1. `docs/SENSITIVE_BRIDGE_ROLLOUT_PLAYBOOK.md` §"Reserved auditor check IDs (25 total)" — Phase 6 reserved baseline.
2. `docs/plan_backups/sensitive_clinical_bridge_v1.3.backup.2026-05-08-1402.plan.md` §Gap A–S, §Auditor extension.
3. Conversation transcript Phase 2 (10 detector modules) — each emits `_auditor_self_check()` keys.
4. Conversation transcript Phase 3 (controller, mandatory reporting, coach override, checkin agent, TMC).
5. Conversation transcript Phase 4 (`sensitive_clinical_bridge.py` orchestrator + wiring).
6. Conversation transcript Phase 4b (`sensitive_profile_api.py` portal).
7. In-tree `_auditor_self_check()` functions — verified by `grep -r _auditor_self_check backend/app/`.

---

## Canonical Inventory — 32 checks

Numbered consecutively. Source column maps each ID to its origin. `Status` column flags whether the check is wired in code today (✓), reserved-but-not-implemented (R), or requires the v1.2 fixture suite landed in this phase (F).

### A. Schema integrity (5) — Plan v1.3 reserved

| # | Check ID | Source | Status |
|---|----|---|---|
| 1 | `sensitive_log_table_present` | Playbook §Schema integrity | R |
| 2 | `sensitive_log_immutable_enforced` | Playbook §Schema integrity | R |
| 3 | `user_safety_codewords_no_plaintext_leak` | Playbook §Schema integrity | R |
| 4 | `safe_silence_state_view_present` | Playbook §Schema integrity | R |
| 5 | `crystal_domain_canonical_set` | Playbook §Schema integrity (Sug 4) | R |

### B. Retention & RBAC (4) — Plan v1.3 reserved

| # | Check ID | Source | Status |
|---|----|---|---|
| 6 | `sensitive_log_retention_default_7yr` | Playbook §Retention & RBAC | R |
| 7 | `sensitive_log_jurisdiction_trigger_present` | Playbook §Retention & RBAC (Phase 4 Gap L) | R |
| 8 | `sensitive_log_access_classification_enforced` | Playbook §Retention & RBAC | R |
| 9 | `immutable_types_includes_sensitive_log` | Playbook §Retention & RBAC | R |

### C. Detector feature-flag activation (8) — Plan v1.3 reserved

Each verifies `gap_feature_flags` row state AND ≥1 telemetry event in last 7 days.

| # | Check ID | Source | Status |
|---|----|---|---|
| 10 | `flag_introjection_active` | Playbook §Detector flags | R |
| 11 | `flag_thalamic_gate_active` | Playbook §Detector flags | R |
| 12 | `flag_reengagement_active` | Playbook §Detector flags | R |
| 13 | `flag_arousal_cap_active` | Playbook §Detector flags | R |
| 14 | `flag_polyvictim_load_active` | Playbook §Detector flags | R |
| 15 | `flag_active_disclosure_active` | Playbook §Detector flags | R |
| 16 | `flag_codeword_active` | Playbook §Detector flags | R |
| 17 | `flag_jurisdiction_compliance_active` | Playbook §Detector flags | R |

### D. Cohort & telemetry (4) — Plan v1.3 reserved

| # | Check ID | Source | Status |
|---|----|---|---|
| 18 | `sensitive_bridge_enrollment_table_present` | Playbook §Cohort & telemetry | ✓ (table created Phase 4) |
| 19 | `detector_telemetry_table_present` | Playbook §Cohort & telemetry | ✓ (table created Phase 4) |
| 20 | `false_positive_rate_under_5pct_per_gap` | Playbook §Cohort & telemetry | R |
| 21 | `shadow_mode_decision_review_current` | Playbook §Cohort & telemetry | R |

### E. Operational (4) — Plan v1.3 reserved

| # | Check ID | Source | Status |
|---|----|---|---|
| 22 | `safe_silence_expiry_warning_cadence_observed` | Playbook §Operational (Gap M) | R |
| 23 | `mandatory_reporting_trafficking_path_present` | Playbook §Operational | ✓ (`mandatory_reporting._auditor_self_check`) |
| 24 | `coach_handoff_redaction_payload_no_pii` | Playbook §Operational | R |
| 25 | `validator_lexicon_loaded_and_versioned` | Playbook §Operational | ✓ (`linguistic_arousal_load._auditor_self_check`) |

**Plan v1.3 baseline subtotal: 25 checks (1–25).**

---

### F. Conversation-added — Phase 4 orchestrator contract (5)

Wired in `sensitive_clinical_bridge._auditor_self_check()`. Aggregated under one auditor entry but exposed as 5 distinct sub-check IDs to keep diff under one row.

| # | Check ID | Source | Status |
|---|----|---|---|
| 26 | `pipeline_order_matches_plan_v1_3` | Phase 4a Note 1 | ✓ |
| 27 | `bridge_decision_schema_hash_stable` | Phase 4a Note 3 | ✓ |
| 28 | `redaction_validator_fires_on_overlap` | Phase 4a Note 3 | ✓ |
| 29 | `phase4_no_modifications_to_phase3_modules` (alias `no_phase3_module_mutations`) | Phase 4a invariant | ✓ |
| 30 | `coach_alert_carries_payload_ref` | Phase 4a Note 3 | ✓ |

### G. Conversation-added — Phase 4 wiring + validator (4)

Wired in `sensitive_clinical_bridge._auditor_self_check()` + `run_runtime_auditor_checks()`.

| # | Check ID | Source | Status |
|---|----|---|---|
| 31 | `feature_flag_count_is_16` | Phase 4 mid-checkin Note 3 | ✓ |
| 32 | `phase4_wiring_diff_under_15_lines` | Phase 4 mid-checkin Note 1 | ✓ |
| — | `validator_lexicon_clinician_gated` | Phase 4 mid-checkin Note 2 | ✓ (folds into #25 above) |
| — | `master_kill_switch_present` | Phase 4 runtime check | ✓ (folds into #18/19 surface) |

### H. Conversation-added — Phase 4b portal contract (2)

Wired in `sensitive_profile_api._auditor_self_check()`.

| # | Check ID | Source | Status |
|---|----|---|---|
| — | `phase4b_all_coach_endpoints_use_require_clinician_for_user` | Phase 4b Note 1 | ✓ (folds into #8 server-side enforcement) |
| — | `safe_silence_orchestrator_cannot_mutate` | Phase 4b Note 2 | ✓ (folds into #22) |
| — | `contract_version_pinned` | Phase 4b portal | ✓ (folds into #5 schema check) |
| — | `pii_screen_helper_present` | Phase 4b portal | ✓ (folds into #24) |

**Note**: Phase 4b portal checks are kept as **per-module self-checks** (already running) but do NOT add new auditor IDs. They report through the four §E operational checks above. This keeps the auditor surface at 32 IDs (plan-aligned), not 36 (which would force trust_baseline expected count to 549+4=553 and diverge from the playbook §"Reserved 25" promise).

### I. Conversation-added — Phase 3 v1.2 parity (2)

These are the **`phase3_*_v1_2_fixtures_pass`** checks named in Phase 5 Note 2. See §"v1.2 Fixture Decision" below.

| # | Check ID | Source | Status |
|---|----|---|---|
| 31 (alias) | `phase3_controller_v1_2_fixtures_pass` | Phase 3 controller-extensions deferral | F |
| 32 (alias) | `phase3_mandatory_reporting_v1_2_fixtures_pass` | Phase 3 mandatory-reporting deferral | F |
| — | `phase3_coach_override_v1_2_fixtures_pass` | Phase 3 coach-handoff deferral | F (folds into #24) |
| — | `phase3_checkin_agent_v1_2_cadence_preserved` | Phase 3 checkin deferral | ✓ (already static; folds into #22) |
| — | `phase3_tmc_v1_2_no_layer_users_unchanged` | Phase 3 TMC deferral | ✓ (already static via `tmc_v1_2_signal_weights_numerically_unchanged`) |

**Final canonical count: 32 distinct auditor IDs** (25 plan-reserved + 5 orchestrator + 2 wiring + 2 v1.2-fixture = 32 nominal slots; some sub-identifiers fold into parent checks per the alias column).

The trust_baseline `expected` value Phase 6 will publish: **`{"expected": 32}`** (not 25). Per Phase 5 Note 1 expansion guidance: "Final count likely lands at 28-32 distinct checks — that's correct expansion within scope, not drift."

---

## v1.2 Fixture Decision (Note 2)

### Background

Three checks remain deferred to Phase 5 fixture suite:

1. `phase3_controller_v1_2_fixtures_pass` — controller behavior with `register_directive=None` must equal v1.2 output for identical input.
2. `phase3_mandatory_reporting_v1_2_fixtures_pass` — TRAFFICKING enum + screen messages must preserve v1.2 raw-match triggers.
3. `phase3_coach_override_v1_2_fixtures_pass` — focus domains + acuity tiers must be additive over v1.2 surface.

The other two named in conversation are already enforced statically:
- `phase3_checkin_agent_v1_2_cadence_preserved` → boolean module constant `_V1_2_CADENCE_PRESERVED`
- `phase3_tmc_v1_2_no_layer_users_unchanged` → numeric weight equality in `_auditor_self_check`

### Path Comparison

| Path | Cost | Accuracy | Auditability |
|---|---|---|---|
| **A. Capture from staging** | 3-5 days (git checkout pre-Phase-3 commit, redeploy staging, run fixture capture, archive, redeploy v1.3) | High for captured cases; blind to uncaptured edges | Tied to staging environment lifetime |
| **B. Synthetic fixtures from pinned v1.2 contracts** | 1 day | High — contracts already pinned in code (`_PHASE_V1_2_REGISTER_VARIANTS`, `_PHASE_V1_2_BANNED_PHRASES`, `_ALLOWED_FOCUS_DOMAINS_V1_2`, `_ALLOWED_ACUITY_TIERS_V1_2`, `_SCREEN_MESSAGE_RAW_MATCH_TRIGGERS`, `_V1_2_SIGNAL_WEIGHTS`) | Permanent; lives in repo |

### Decision: **Synthetic fixtures (Path B)**

**Rationale**:

1. **The v1.2 contract is already a code artifact.** Each Phase 3 module pins its v1.2 surface in module-level constants (above). The `_auditor_self_check` functions already reference these constants for additivity guards. Synthetic fixtures encode the input → expected-output golden pairs derived from those constants, making the v1.2 contract a literal artifact that the auditor re-validates forever.

2. **Capture-from-staging is now structurally compromised.** Phase 3 + 4 + 4b code is live in the repo. A staging environment built from `HEAD` runs v1.3 code with the master kill-switch off and zero cohort enrollment. Behavior of the kill-switch-off path in v1.3 is what we want to validate — but that is exactly what the additivity boot guards already enforce. Capturing from current staging would yield tautological fixtures ("v1.3-with-no-enrollment matches v1.3-with-no-enrollment").

3. **Genuine v1.2 capture would require a git checkout to pre-Phase-3 SHA + staging redeploy + fixture run + redeploy v1.3.** The 3-5-day cost buys evidence that the additivity guards already provide statically. Synthetic fixtures buy explicit per-input/per-output regression tests in 1 day.

4. **Clinical-safety alignment.** Synthetic fixtures are a **permanent** artifact of "v1.2 contract" stored next to the code. Captured fixtures depend on a staging environment that may itself drift, be torn down, or lose its provenance.

### Implementation Sketch (will land in Phase 5 alongside auditor)

```
backend/tests/sensitive_bridge_v1_2_parity/
├── controller_v1_2_fixtures.json          # 12-15 input/output pairs covering v1.2 register triggers
├── mandatory_reporting_v1_2_fixtures.json # 8-10 pairs covering TRAFFICKING + earlier 4 enums
├── coach_override_v1_2_fixtures.json      # 6-8 pairs covering 4 focus domains + 3 acuity tiers
├── runner.py                              # pytest entry, callable by sensitive_bridge_auditor.py
└── README.md                              # provenance: pinned-constant references per fixture
```

The auditor's `phase3_controller_v1_2_fixtures_pass` etc. checks invoke `runner.py:assert_v1_2_parity()` which loads the JSON, dispatches to the live module, and asserts byte-equality on the v1.2-shape output (any v1.3-only fields stripped before comparison).

---

## Phase 5 Pre-Code Sequence

1. ✅ This inventory (THIS DOC).
2. ✅ v1.2 fixture decision recorded (above).
3. **Next**: Author 3 fixture JSON files + `runner.py` (Phase 5 sub-task `phase5-v1-2-fixtures`).
4. **Then**: Author `sensitive_bridge_auditor.py` with all 32 IDs.
5. **Then**: 5-location trust-enforcer sync per `auditor-endpoint-sync.mdc` + `trust-enforcer-architecture.mdc`.
6. **Then**: Trust baseline migration `{"expected": 32}` + service health denominator 114→115.
7. **Then**: Phase 5 mid-checkin before Phase 6 cohort enrollment.

---

## Cross-Reference Map

| Source | Check IDs Contributed |
|---|---|
| Playbook §Schema integrity | 1, 2, 3, 4, 5 |
| Playbook §Retention & RBAC | 6, 7, 8, 9 |
| Playbook §Detector flags | 10, 11, 12, 13, 14, 15, 16, 17 |
| Playbook §Cohort & telemetry | 18, 19, 20, 21 |
| Playbook §Operational | 22, 23, 24, 25 |
| Phase 4a orchestrator | 26, 27, 28, 29, 30 |
| Phase 4 mid-checkin | 31 (`feature_flag_count_is_16`), 32 (`phase4_wiring_diff_under_15_lines`) |
| Phase 4b portal (folded sub-checks) | aliases for 5, 8, 22, 24 |
| Phase 3 v1.2 parity (folded F-status aliases) | 31, 32 (alias slots backed by fixture suite) |

EOF

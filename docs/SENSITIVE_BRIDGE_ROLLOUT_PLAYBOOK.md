# Sensitive Clinical Bridge — Rollout & Rollback Playbook

**Version**: 1.0
**Date**: 2026-05-08
**Audience**: Engineers, on-call admin, supervising clinician

**Doc-set role**: This is the **operational authoritative** document. For the
clinical authority see `docs/SENSITIVE_CLINICAL_BRIDGE_GUIDELINES_2026-05-08.md`
§1–20. For the technical spec see plan v1.3
(`docs/plan_backups/sensitive_clinical_bridge_v1.3.backup.2026-05-08-1402.plan.md`)
§Gap A–S. When operational content here conflicts with either, this doc wins
for runtime decisions and deferral to the others applies for clinical or spec
questions.

**Companion docs**:
- `docs/SENSITIVE_CLINICAL_BRIDGE_GUIDELINES_2026-05-08.md` (clinical authority)
- `docs/plan_backups/sensitive_clinical_bridge_v1.3.backup.2026-05-08-1402.plan.md` (spec authority)
- `.cursor/rules/trust-100-percent.mdc`
- `.cursor/rules/deployment-trust-100-percent.mdc`
- `.cursor/rules/git-production-deployment.mdc`

This playbook covers Gap F (rollback + canary rollout) and Gap H (6-phase deployment).

---

## 0. First Principle

**Survivor safety beats deployment velocity.** If any phase observation reveals harm risk, halt the rollout. Rolling back is the safe move.

---

## 1. Phase Map

| Phase | Window | Content | Promotion gate |
|---|---|---|---|
| 1 | Days 1–7 | Migrations 202–208 + 2 docs (this + foundational) | All migrations apply cleanly on staging clone; both docs reviewed by clinician |
| 2 | Days 8–21 | Detector modules (audit-only, no orchestrator wiring) | Each detector unit-tested with synthetic profiles; CI green |
| 3 | Days 22–35 | Therapeutic controller register variants + mandatory reporting + coach handoff + check-in extensions + TMC polyvictim signals | Synthetic-scenario integration tests green; clinician sign-off on register variants |
| 4 | Days 36–49 | Orchestrator + validator Layer 8 + wiring + feature flags + telemetry tables | Shadow-mode infrastructure ready; orchestrator p95 < 200ms in CI bench |
| 5 | Days 50–63 | Clinician portal Flutter + REST + data export + crystal corpus | Two-clinician sign-off on lexicon + crystals; portal acceptance test passes |
| 6 | Days 64–77 (shadow) → 78–84 (pilot) → 85+ (gradual GA) | Auditor (29th) + 14-day shadow mode + pilot cohort (5 → 25 → 100 → all) | Per-gap: 7-day observation window with <5% false-positive rate at each cohort step; clinician GA sign-off required |

Total: ~10 weeks before broad GA. Per the user's directive — *this is not a contest of speed*.

---

## 2. Per-Phase Pre-Flight

Before each phase begins, run this checklist:

- [ ] Previous phase's observation window fully elapsed (no early advancement).
- [ ] All previous phase's tasks marked complete in todo list.
- [ ] No open critical or high-severity bugs from previous phase.
- [ ] Trust dashboard at 100% (524/524 + future denominator changes).
- [ ] `.env` audit token + Redis healthy.
- [ ] Backup of plan file taken (`docs/plan_backups/`).
- [ ] Backup of prior phase's docs / config taken.
- [ ] On-call admin briefed on next phase scope.
- [ ] Clinician available for sign-off if phase requires it.

---

## 3. Migration Application Order

Migrations 202 → 208 must apply **in numerical order**. Each is idempotent, but 203–208 reference foundation set by 202.

### Staging clone first

```bash
ssh root@68.183.168.75 "docker exec nate_postgres pg_dump -U nate_admin little_nate > /tmp/pre_migration_202_$(date +%Y%m%d_%H%M).sql.gz"
```

Then on a staging instance (not production):

```bash
for f in 202 203 204 205 206 207 208; do
  echo "Applying migration ${f}..."
  psql -U nate_admin -d little_nate_staging -v ON_ERROR_STOP=1 \
    -f backend/migrations/${f}_*.sql || { echo "FAILED at ${f}"; exit 1; }
done
```

### Production application

Only after staging passes and clinician has reviewed both docs:

```bash
ssh root@68.183.168.75 "cd /opt/clinical-sovereignty-lab && \
  for f in 202 203 204 205 206 207 208; do \
    docker exec -i nate_postgres psql -U nate_admin -d little_nate -v ON_ERROR_STOP=1 \
      -f /opt/clinical-sovereignty-lab/backend/migrations/${f}_*.sql || break; \
  done"
```

**STOP if any migration fails.** Do not proceed to dependent migrations. Roll back per Section 4.

---

## 4. Per-Migration Rollback

All migrations are additive. Rollback removes the new objects without touching existing data.

### 202 — sensitive_bridge_log core

```sql
DROP INDEX IF EXISTS idx_sensitive_log_user_recent;
DROP INDEX IF EXISTS idx_sensitive_log_event_type;
DROP INDEX IF EXISTS idx_sensitive_log_retention;
DROP INDEX IF EXISTS idx_sensitive_log_severity;
DROP TABLE IF EXISTS sensitive_bridge_log;
```

### 203 — user_linguistic_baseline + coercive_voice_profiles

```sql
DROP TABLE IF EXISTS coercive_voice_profiles;
DROP TABLE IF EXISTS user_linguistic_baseline;
```

### 204 — user_safety_codewords

```sql
DROP INDEX IF EXISTS idx_user_safety_codewords_active;
DROP TABLE IF EXISTS user_safety_codewords;
-- pgcrypto extension intentionally left enabled (used elsewhere)
```

### 205 — user_trigger_dates

```sql
DROP INDEX IF EXISTS idx_trigger_dates_match;
DROP TABLE IF EXISTS user_trigger_dates;
```

### 206 — user_polyvictimization_layers

```sql
DROP INDEX IF EXISTS idx_polyvictim_user_active;
DROP TABLE IF EXISTS user_polyvictimization_layers;
```

### 207 — user_legal_status

```sql
DROP INDEX IF EXISTS idx_legal_status_upcoming;
DROP TABLE IF EXISTS user_legal_status;
```

### 208 — safe_silence_mode_state seed

The seed UPDATE is reversed by clearing the JSONB key. Idempotent.

```sql
DROP VIEW IF EXISTS safe_silence_mode_active_users;
UPDATE users
SET profile_data = profile_data - 'safe_silence_mode_state'
WHERE profile_data ? 'safe_silence_mode_state';
```

### Full Phase 1 rollback (single command)

```sql
BEGIN;
DROP VIEW IF EXISTS safe_silence_mode_active_users;
UPDATE users SET profile_data = profile_data - 'safe_silence_mode_state'
  WHERE profile_data ? 'safe_silence_mode_state';
DROP INDEX IF EXISTS idx_legal_status_upcoming;
DROP TABLE IF EXISTS user_legal_status;
DROP INDEX IF EXISTS idx_polyvictim_user_active;
DROP TABLE IF EXISTS user_polyvictimization_layers;
DROP INDEX IF EXISTS idx_trigger_dates_match;
DROP TABLE IF EXISTS user_trigger_dates;
DROP INDEX IF EXISTS idx_user_safety_codewords_active;
DROP TABLE IF EXISTS user_safety_codewords;
DROP TABLE IF EXISTS coercive_voice_profiles;
DROP TABLE IF EXISTS user_linguistic_baseline;
DROP INDEX IF EXISTS idx_sensitive_log_user_recent;
DROP INDEX IF EXISTS idx_sensitive_log_event_type;
DROP INDEX IF EXISTS idx_sensitive_log_retention;
DROP INDEX IF EXISTS idx_sensitive_log_severity;
DROP TABLE IF EXISTS sensitive_bridge_log;
COMMIT;
```

This SHOULD only be run after explicit admin approval if Phase 1 must be fully reverted before any production data has accumulated. Once production data exists in `sensitive_bridge_log`, full rollback is forbidden — instead, the schema is preserved and code is reverted to bypass the orchestrator.

---

## 5. Per-Detector Feature Flags (Gap F)

Once Phase 4 lands, every detector ships behind a flag. Default OFF.

**Flag set (added in Phase 4):**

```python
GAP_FEATURE_FLAGS = {
  "gap_introjection_enabled": False,
  "gap_thalamic_gate_enabled": False,
  "gap_reengagement_enabled": False,
  "gap_arousal_cap_enabled": False,
  "gap_polyvictim_load_enabled": False,
  "gap_dual_diagnosis_enabled": False,
  "gap_active_disclosure_enabled": False,
  "gap_codeword_enabled": False,
  "gap_trigger_dates_enabled": False,
  "gap_legal_status_enabled": False,
  "gap_embodiment_phase_enabled": False,
  "gap_jurisdiction_compliance_enabled": False,
  "gap_minor_survivor_protections_enabled": False,
  "gap_parenting_no_pathologization_enabled": False,
  "gap_rj_companioning_enabled": False,
  "gap_cultural_context_enabled": False,
}
```

**Per-user override** lives in `sensitive_bridge_enrollment(user_id, gap_features_enabled JSONB, cohort_label, enrolled_at)` (Phase 4 migration). User-level flag wins over global flag.

### Disabling a flag at runtime

```bash
# Via admin REST endpoint (Phase 6)
curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://api.sovereignsanctuary.net/api/admin/sensitive-bridge/feature-flag \
  -d '{"flag":"gap_introjection_enabled","value":false,"reason":"FP rate >5% over 7d"}'
```

### Auto-disable trigger

`detector_telemetry` aggregator runs hourly. If any flag's classifications over the last 7 days show false-positive rate > 5% (from clinician review queue), the flag auto-disables globally and an admin alert fires.

---

## 6. Cohort Phasing (Gap F + Gap H)

| Cohort | Size | Window | Promotion criterion |
|---|---|---|---|
| Pilot | 5 users | 7 days | <5% FP rate per gap; clinician sign-off |
| Early | 25 users | 7 days | Same |
| Broad | 100 users | 7 days | Same |
| GA | All eligible | Open | Same; per-gap continuous monitoring |

Enrollment uses the `sensitive_bridge_enrollment` table. A user is in cohort N if their `cohort_label` matches the active cohort tag.

---

## 7. Shadow Mode (Gap I — Phase 6)

For 14 days after Phase 4 wiring lands, the orchestrator runs in **shadow mode**:

- `sensitive_clinical_bridge.evaluate_disclosure()` executes the full 18-step pipeline.
- The returned `BridgeDecision` is logged to `sensitive_bridge_log` with `event_type = 'disclosure_evaluated'` and a `shadow_mode=true` flag in `decision_summary`.
- The decision is **not applied** to the controller. The controller sees a no-op decision.
- Clinicians review the shadow log daily and grade decisions.
- After 14 days with clinician sign-off and <5% false-positive rate per gap, individual gaps are promoted from shadow → live one at a time, each with its own 7-day observation.

---

## 8. Container Restart Discipline

Per `deployment-trust-100-percent.mdc`:

- Avoid restarting between HH:50 and HH:10 of audit hours (4:50–5:10, 16:50–17:10, 22:50–23:10 UTC).
- After Phase 1 migrations, no backend restart is required (schema-only changes).
- Phase 2+ code changes require `docker compose -f docker-compose.prod.yml up -d --build` per `git-production-deployment.mdc`.
- After every restart, run the post-deploy verification chain:
  - 114/114 (or new denominator) services healthy
  - No "does not exist" schema errors
  - Bridge POSTGRES_HOST = postgres
  - ENVIRONMENT match between backend + bridge

---

## 9. Trust Audit Sync (Phase 6)

When the 29th auditor (`sensitive_bridge_auditor.py`) lands, the 5-location sync per `trust-enforcer-architecture.mdc` is mandatory:

| # | Location | Update |
|---|---|---|
| 1 | `TAB_ENDPOINTS` in `sensitive_bridge_auditor.py` | 25 checks across 5 tabs |
| 2 | `AUDITOR_ACTIVITY_TYPES` in `trust_enforcer.py` | `"sensitive_bridge_audit_sent"` |
| 3 | `AUDITOR_LABELS` in `trust_enforcer.py` | `"Sensitive Clinical Bridge"` |
| 4 | `_baseline_key_for()` in `trust_enforcer.py` | `"sensitive_bridge_check_count"` |
| 5 | `trust_baseline` row | `{"expected": 25}` |

### Reserved auditor check IDs (25 total)

The 25 checks are reserved by ID now so future migration drift cannot displace them.
Phase 6 implementation must use these exact IDs:

**Schema integrity (5):** `sensitive_log_table_present`, `sensitive_log_immutable_enforced`,
`user_safety_codewords_no_plaintext_leak`, `safe_silence_state_view_present`,
`crystal_domain_canonical_set` *(Suggestion 4 — drift guard for nate_intelligence_crystals.domain;
scans DISTINCT domain values monthly, alerts if any value is outside the canonical 5
+ legacy set; baseline established at first run)*.

**Retention & RBAC (4):** `sensitive_log_retention_default_7yr`,
`sensitive_log_jurisdiction_trigger_present` *(Phase 4 Gap L)*,
`sensitive_log_access_classification_enforced`, `immutable_types_includes_sensitive_log`.

**Detector flags (8):** one per critical detector flag — verifies global flag state
and at least one telemetry event in the last 7 days. `flag_introjection_active`,
`flag_thalamic_gate_active`, `flag_reengagement_active`, `flag_arousal_cap_active`,
`flag_polyvictim_load_active`, `flag_active_disclosure_active`, `flag_codeword_active`,
`flag_jurisdiction_compliance_active`.

**Cohort & telemetry (4):** `sensitive_bridge_enrollment_table_present`,
`detector_telemetry_table_present`, `false_positive_rate_under_5pct_per_gap`,
`shadow_mode_decision_review_current`.

**Operational (4):** `safe_silence_expiry_warning_cadence_observed`,
`mandatory_reporting_trafficking_path_present`, `coach_handoff_redaction_payload_no_pii`,
`validator_lexicon_loaded_and_versioned`.

Service health denominator changes from 114 → 115. Update:
- `_service_checks` in `main.py`
- `.cursor/rules/service-health-49-49.mdc`
- `.cursor/rules/service-health-124.mdc`
- `.cursor/rules/trust-100-percent.mdc` (524 + 25 = 549)

Stagger: next available 5s slot, currently 295s is taken — use 300s ceiling (verify no other agent at 300s first).

---

## 10. Backup Cadence

| Artifact | Cadence | Location |
|---|---|---|
| Plan file | Before any plan amendment | `docs/plan_backups/sensitive_clinical_bridge_v*.backup.<ts>.plan.md` |
| Foundational guidelines doc | Before any clinical content change | `docs/foundation_backups/` |
| Database (full) | Daily 02:00 UTC (existing pg_dump cadence) | Existing backup target |
| Database (pre-migration) | Manually before each migration | `/tmp/pre_migration_<n>_<ts>.sql.gz` then move to durable storage |
| Validator lexicon | Before any lexicon merge | Git history (version-controlled) |
| Crystal corpus | Before any bulk re-ingestion | Git history (JSON files in `data/crystals/`) |

---

## 11. Communication Protocol

When entering or exiting any phase:

1. Engineer posts in `#sovereign-deploys` channel (or equivalent): "Phase N starting" with checklist link.
2. Clinician confirms availability for sign-off if phase requires it.
3. On-call admin acknowledges.
4. Engineer pastes git diff summary for the phase's changes.
5. After phase completion, engineer posts: "Phase N complete; observation window starts <ts>; advancement gate at <ts>."

If anything goes sideways mid-phase:

1. Engineer pastes the failure in the channel.
2. Engineer pauses any in-flight work.
3. On-call admin decides: pause / rollback / fix-forward.
4. Decision logged in this playbook's runtime log section (Section 13).

---

## 12. Definition of Done (Per Phase)

A phase is **done** only when ALL of:
- All todo items for the phase are marked `completed`.
- CI is green (lint + unit + integration + bench).
- Clinician sign-off captured (where required).
- Observation window has fully elapsed.
- Documentation reflects the phase's changes.
- Backup of any modified docs has been taken.

A phase is **NOT done** if:
- A todo item is `cancelled` without explicit user approval.
- CI is yellow (warnings unacknowledged).
- Production showed degraded behavior at any point during the phase.
- Anyone who needs to sign off has not signed off.

---

## 13. Runtime Log

This section is appended to during execution. Format: `<ISO timestamp> [<phase>] <event>`.

```
2026-05-08T18:02:00Z [Phase 1] Plan v1.3 backup created at docs/plan_backups/sensitive_clinical_bridge_v1.3.backup.2026-05-08-1402.plan.md
2026-05-08T18:02:00Z [Phase 1] Migrations 202-208 written to backend/migrations/
2026-05-08T18:02:00Z [Phase 1] Foundational guidelines doc written to docs/SENSITIVE_CLINICAL_BRIDGE_GUIDELINES_2026-05-08.md
2026-05-08T18:02:00Z [Phase 1] Rollback playbook written to docs/SENSITIVE_BRIDGE_ROLLOUT_PLAYBOOK.md
2026-05-08T18:25:00Z [Phase 1] Review pass v1.0.1 — applied 7 reviewer suggestions:
  - 202: documented Phase 4 Gap L jurisdiction-trigger amendment for retained_until (Sug 2)
  - 202: added gap_feature_auto_disabled to event_type CHECK (33 events total) (Sug 3)
  - 202: documented crystal_domain_canonical_set drift guard (Sug 4)
  - 202: column comment locking retention modification policy (Sug 2)
  - 204: column comments locking codeword_salt application-side generation policy (Sug 5)
  - 204: column comment locking constant-time comparison policy (Sug 5)
  - 208: documented backfill scope and corrective UPDATE template if drift detected (Sug 6)
  - Guidelines: corrected event_type count 40 → 33; added doc-set role cross-ref (Sug 3, 7)
  - Playbook: added doc-set role cross-ref; reserved 25 auditor check IDs incl.
    crystal_domain_canonical_set (Sug 4, 7)
  Confirmed CLEAN: Sug 1 (codeword_type present line 24); Sug 5 hash policy
  (no server-side default on codeword_salt was ever present).
```

Future entries appended chronologically by the executing engineer.

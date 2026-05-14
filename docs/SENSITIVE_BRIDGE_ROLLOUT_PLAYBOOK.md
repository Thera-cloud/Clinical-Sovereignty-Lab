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

## 4a. Do NOT Rollback For These (Note 2)

Rollback is irreversible loss of operational state and clinician trust. The
following symptoms **look like** rollback opportunities at 2am but are not.
Saving the on-call admin from a pager-call overreaction during pilot is the
purpose of this section.

For each: the **symptom**, why it looks like a rollback signal, and the
**right response** that is not a rollback.

### 4a.1 — Single false-positive on a single user

**Symptom:** Clinician flags one shadow-mode decision as a false positive.
A specific user's decision_summary shows a register dispatch the clinician
disagrees with.

**Looks like:** Detector misfire requiring rollback of the offending detector.

**Why it isn't:** A single clinician flag on a single row is one data point.
Rollback overreacts. The detector_telemetry pipeline + the auto-disable
trigger (Section 5) exist precisely to absorb single FP rows without manual
intervention. One FP per detector per week is well within the 5%-over-20-sample
gate; only a sustained pattern across multiple windows arms the auto-disable.

**Right response:** Mark the row in the clinician review queue as
`classification = 'false_positive'`, `clinician_reviewed = TRUE`. Telemetry
will pick it up on the next agent cycle. If the pattern continues, the
multi-window agreement check will arm the disable.

---

### 4a.2 — Clinician disagreement with a register dispatch

**Symptom:** Clinician reviews a `register_assigned` event in
`sensitive_bridge_log` and disagrees with the register the orchestrator
chose for a specific disclosure.

**Looks like:** Controller bug requiring revert of `therapeutic_controller.py`
register variant logic.

**Why it isn't:** Register disagreement is a **clinical review** outcome, not
a software defect. The lexicon and register-mapping rules live in clinician-
authored config (`data/sensitive_domain_validator_lexicon_*.json` per Gap D),
not in code. Rolling back code does not change the register mapping.

**Right response:** Use the lexicon-update workflow per Gap D — open a
clinician PR against the lexicon JSON, route through two-clinician sign-off,
land via `bulk_crystal_ingestion.py`. Code stays put.

---

### 4a.3 — Performance regression in non-bridge code

**Symptom:** API p95 latency creeps up after a deploy that touched the bridge
plus other modules. Bridge orchestrator is in the trace.

**Looks like:** Bridge orchestrator overhead requires rollback of the
sensitive bridge.

**Why it isn't:** The bridge appearing in a trace does not make it the cause.
The orchestrator's p95 budget is < 200ms (verified in CI bench, Phase 4 gate)
and the kill-switch at `app_settings.sensitive_bridge_master_enabled = false`
provides a one-flag bypass that takes < 5 seconds to flip. Rolling back the
bridge to fix someone else's bug deletes operational state we will not get
back cheaply.

**Right response:** Flip the master kill switch first as a diagnostic
(orchestrator returns neutral BridgeDecision — equivalent to "bridge
removed from request path" without the data loss). If latency recovers,
the bridge is involved; bisect bridge changes. If latency does not recover,
the bridge is exonerated — investigate the other module. Either way, no
schema rollback.

```bash
# Diagnostic kill switch (NOT a rollback — easily reversed)
curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://api.sovereignsanctuary.net/api/admin/sensitive-bridge/feature-flag \
  -d '{"flag":"sensitive_bridge_master_enabled","enabled":false,"reason":"latency diagnostic"}'
```

---

### 4a.4 — Spike in `disclosure_evaluated` events

**Symptom:** `sensitive_bridge_log` shows 5x normal volume of
`event_type = 'disclosure_evaluated'` rows after a pilot cohort enrollment
expansion.

**Looks like:** Detector firing too aggressively, producing event noise.

**Why it isn't:** `disclosure_evaluated` fires on **every** orchestrator
invocation, not on detector positive matches. A spike in `disclosure_evaluated`
means more disclosures are being evaluated, which is **the pilot working** —
more enrolled users, more chat traffic, more orchestrator calls. The signal
to watch for detector-firing volume is `event_type` values like
`introjection_detected`, `codeword_triggered`, `arousal_cap_triggered` — not
the umbrella `disclosure_evaluated` event.

**Right response:** None. Pilot is healthy. If detector-specific event types
also show 5x volume **and** the FP rate from clinician review jumps, that is
the signal — and the auto-disable trigger (Section 5) will catch it without
any manual intervention.

---

### 4a.5 — Telemetry agent armed an auto-disable

**Symptom:** Admin receives a `coach_alert_high` notification:
"sensitive_bridge_telemetry_agent: armed auto-disable for gap_X (commits in 30 min)."

**Looks like:** Detector failure requiring rollback of the detector module.

**Why it isn't:** Arming is the safeguard working. The 30-minute countdown
exists for human review, not for panic. If the multi-window snapshot in the
alert payload shows a real sustained FP regression, **let the disable
commit** — that is the entire purpose of the safeguard. If clinician review
of the FP rows shows the rate is calibration drift (not a detector bug),
**cancel the disable** via the REST endpoint and re-classify the underlying
telemetry rows.

**Right response:** Read the multi-window snapshot in the alert payload.
If the breach is real, do nothing — let the disable commit and use the
re-enable resolved-telemetry gate to bring it back when fixed. If the
breach is artifactual, cancel via REST and re-classify the telemetry. **Do
not** revert detector code in either case.

---

### 4a.6 — Failed Phase-1 migration on staging

**Symptom:** Migration 203 fails on staging clone with a CHECK-constraint
error related to `sensitive_bridge_log.event_type`.

**Looks like:** Time to abandon the bridge and roll back Phase 1.

**Why it isn't:** Migrations 209 and 210 contain self-healing `DO $$` blocks
that extend the `event_type` CHECK constraint to include the new event
types. If a CHECK error occurs, the right response is to verify the
self-healing block ran (read the migration source for the `IF NOT EXISTS`
guard), not to drop tables.

**Right response:** Inspect `pg_constraint` for the current constraint
definition. If the new event types are missing, re-run the migration in a
transaction — the `IF NOT EXISTS` self-healing logic is idempotent. If the
re-run still fails, **then** open the rollback runbook in Section 4.

---

### 4a.7 — Auditor reports `META_ORDERING_OBSERVED != _CHECK_ORDER`

**Symptom:** `sensitive_bridge_audit_sent` rows show
`audit_check_ordering_cheap_first` failing.

**Looks like:** Auditor itself is broken; rollback the auditor.

**Why it isn't:** This is the META check **doing its job**. It catches a
maintainer who reordered checks "for readability" and broke the cost-tier
ordering contract. The fix is to revert the reorder, not the auditor.

**Right response:** `git log -p backend/app/services/sensitive_bridge_auditor.py`
to find the commit that reordered `_CHECK_ORDER` or the `_run_tierN` methods.
Revert that single commit. Do not revert the auditor itself.

---

### Summary table

| # | Symptom | Why not rollback | Right response |
|---|---|---|---|
| 4a.1 | Single FP on one user | Telemetry will catch real patterns | Re-classify in clinician review queue |
| 4a.2 | Clinician disagrees with register | Code change won't fix lexicon mapping | Lexicon-update workflow (Gap D) |
| 4a.3 | Latency regression w/ bridge in trace | Kill switch is the diagnostic | Flip `sensitive_bridge_master_enabled=false` |
| 4a.4 | `disclosure_evaluated` 5x spike | That's the pilot working | Watch detector-specific event types instead |
| 4a.5 | Telemetry armed an auto-disable | Arming is the safeguard | Let it commit, or cancel + re-classify |
| 4a.6 | Phase-1 migration CHECK error | Migrations are self-healing | Re-run; rollback only if re-run fails |
| 4a.7 | META ordering check fails | META is doing its job | Revert the offending reorder commit |

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

### Auto-disable trigger (Note 1 — three implementation safeguards)

The auto-disable trigger has the **highest blast radius** of any single piece of
code in this build: a single nightly job can disable an entire detector for all
enrolled users. Three safeguards prevent off-by-one or window-boundary bugs from
disabling a clinically-correct detector.

**Owner:** `backend/app/services/sensitive_bridge_telemetry_agent.py`.
**REST surface:** `/api/admin/sensitive-bridge/auto-disable/*` and
`/api/admin/sensitive-bridge/feature-flag` (admin-only). Auditor invariant:
`auto_disable_reenable_requires_resolved_telemetry` (Tier-1 slot 11).

**Default posture:** `app_settings.sensitive_bridge_telemetry_agent.paused = TRUE`.
Migration 210 ships the agent **paused** so nothing auto-disables until an admin
explicitly enables it during pilot. This is the **fail-safe-off** default — if
the agent module crashes, nothing happens to the feature flags either.

#### Safeguard 1 — Multi-window agreement (24h, 72h, 7d)

`false_positive_rate` is computed across three trailing windows (last 24h, 72h, 7d).
A flag is only **armed** for auto-disable if **all three windows agree** on the
threshold breach (rate > 0.05 AND clinician-reviewed sample >= 20 in each window).

| Pattern | Interpretation | Action |
|---|---|---|
| 24h breach + 72h ok + 7d ok | Acute spike, possibly a single bad cohort hour | Telemetry continues; no arm |
| 24h breach + 72h breach + 7d ok | Recent regression, real but not yet established | Telemetry continues; no arm |
| 24h breach + 72h breach + 7d breach | Persistent regression across all windows | **ARM** — proceed to safeguard 2 |
| Any window has reviewed sample < 20 | Insufficient evidence | Telemetry continues; no arm |

Single-window breach without consistency = noise, not signal. The window set is
configured in `app_settings.sensitive_bridge_telemetry_agent.windows` and may
only be widened (not narrowed) without admin approval.

#### Safeguard 2 — Alert + 30-minute admin override countdown

When a flag is armed, the agent does **not** disable immediately. It:

1. Writes a row to `detector_auto_disable_state` with `state = 'armed'`,
   `armed_at = NOW()`, and `commit_at = NOW() + 30 minutes`.
2. Emits `coach_alert_high` to **all admins** with the multi-window snapshot
   embedded in the payload (no PII; `payload_ref` only).
3. Writes a `sensitive_bridge_log` event with
   `event_type = 'auto_disable_armed'` and `severity = 'warning'`.
4. **Blocks for 30 minutes**. During this window, an admin may cancel via:
   ```bash
   curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" \
     "https://api.sovereignsanctuary.net/api/admin/sensitive-bridge/auto-disable/<gap_flag>/cancel" \
     -d '{"reason":"clinician confirmed FP cluster is calibration drift, not detector bug"}'
   ```
   Cancellation moves the row to `state = 'cancelled'` and writes
   `auto_disable_cancelled` to the audit log.
5. If no cancellation arrives, the next agent cycle observes `commit_at <= NOW()`
   and **only then** flips
   `app_settings.sensitive_bridge_global_gap_flags->{gap_flag} = false`,
   sets `state = 'disabled'` with `disabled_at = NOW()`, and writes
   `auto_disable_committed` to the audit log.

30 minutes of human-in-the-loop on a clinical-safety-critical disable is worth
the friction. Plan v1.3 originally said "auto-disable then alert"; we ship
"alert + countdown to disable + admin can cancel."

#### Safeguard 3 — Re-enable requires resolved telemetry

Re-enabling an auto-disabled flag requires explicit admin action **and** fresh
telemetry showing the underlying issue is resolved. The REST endpoint
`POST /api/admin/sensitive-bridge/feature-flag` with `enabled=true` enforces
the gate via `assert_reenable_telemetry_resolved()`:

- Reviewed-sample count after `disabled_at` must be >= 20.
- Reviewed FP rate after `disabled_at` must be <= 0.05.

Failures return `409 Conflict` with body
`{"error":"reenable_blocked_telemetry_unresolved","detail":<reason>,"snapshot":<rates>}`.
The admin cannot override this gate via REST; if the telemetry is genuinely a
false alarm, the path is to re-classify the offending telemetry rows
(through the clinician review queue), then retry the re-enable.

The auditor check `auto_disable_reenable_requires_resolved_telemetry`
(Tier-1 slot 11) verifies: (a) the gate function is importable, (b) the
exception class exists, (c) the agent's default posture is `paused=true`. If
any of these fail, the auditor emits `severity=error` and the trust enforcer
flags the row.

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
| 1 | `_CHECK_ORDER` in `sensitive_bridge_auditor.py` | 33 inventory + 1 META = **34 checks** |
| 2 | `AUDITOR_ACTIVITY_TYPES` in `trust_enforcer.py` | `"sensitive_bridge_audit_sent"` |
| 3 | `AUDITOR_LABELS` in `trust_enforcer.py` | `"Sensitive Clinical Bridge"` |
| 4 | `_baseline_key_for()` in `trust_enforcer.py` | `"sensitive_bridge_check_count"` |
| 5 | `trust_baseline` row | `{"expected": 34}` (META is a real auditor entry; do not exclude) |

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

**Telemetry agent gate (1):** `auto_disable_reenable_requires_resolved_telemetry`
*(Phase 5 Note 1 safeguard #3 — verifies the resolved-telemetry gate is intact
and the telemetry agent ships PAUSED).* Tier-1 slot 11.

Service health denominator changes from 114 → 116 (+1 auditor + 1 telemetry agent). Update:
- `_service_checks` in `main.py` (+2 entries)
- `.cursor/rules/service-health-49-49.mdc`
- `.cursor/rules/service-health-124.mdc`
- `.cursor/rules/trust-100-percent.mdc` (524 + 34 = 558)

Auditor stagger: 305s (3x daily). Telemetry agent stagger: 320s (cycles
hourly when unpaused). 320 is within the 300s auditor ceiling guidance because
the telemetry agent is **not** an auditor — it is a long-running background
observer with its own poll interval.

#### Observation cadence during pilot (Observation 3)

3x daily auditor cadence = ~8h between cycles, which is **insufficient**
granularity to detect drift before cohort_25 promotion during the 14-day
shadow-mode pilot. The cadence choice is:

**Decision (locked for pilot launch):** keep the auditor at 3x daily standard
cadence and let the **telemetry agent** do the high-frequency observation
(hourly cycles when unpaused). Rationale: the auditor is a contract surface
scorecard, not a drift detector; the telemetry agent is purpose-built for
continuous observation and emits its own audit-log events
(`auto_disable_armed`, `auto_disable_committed`, `auto_disable_cancelled`,
`auto_disable_reenabled`) that the auditor's Tier-3
`false_positive_rate_under_5pct_per_gap` check reads on its standard cadence.

Alternative considered and rejected: bumping the auditor to 6x daily during
pilot. Rejected because (a) the auditor is shared infrastructure and changing
its cadence has cascade effects on stagger budgets, (b) the telemetry agent's
hourly cycle gives 24x granularity vs the auditor's 3x.

Re-evaluate this decision after cohort_25 promotion. If drift signal volume
warrants it, revisit raising the auditor cadence then.

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

## 13. Sole-Clinician Deployment Mode

**Added:** Migration 214 (2026-05-10).
**Owner:** Lead clinician (Dr. Nevedal; account `CoachN` / `DrNevedal1`).
**Status column:** `coach_profiles.clinician_authorization_type IN
('sole_lead', 'multi_clinician_team')`. Default is
`'multi_clinician_team'` — the strict gate. Only the lead clinician's
row is backfilled to `'sole_lead'`.

### 13.1 What this mode changes

The Sensitive Clinical Bridge's two-step gate (Plan v1.3 §Gap A) was
written for clinics with **two or more clinicians on duty**. A single-
clinician practice cannot satisfy "different actor on approve" without
inventing a fictitious second account. `'sole_lead'` is a deliberately
narrow exemption that:

| Surface                                    | `multi_clinician_team` (default)                                                  | `sole_lead`                                                                                                                                                                  |
| ------------------------------------------ | --------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `safe_silence_mode` approve, same actor    | **REJECTED** with `multi_clinician_required`                                      | **ALLOWED** *iff* the approve session is a different login session (different bearer-token hash) than the proposal session.                                                  |
| `safe_silence_mode` approve, same session  | **REJECTED** with `same_session_violation`                                        | **REJECTED** with `same_session_violation` — *not relaxed*.                                                                                                                  |
| Codeword precondition (b)                  | Required: ≥1 active codeword                                                      | Required: ≥1 active codeword — *not relaxed*.                                                                                                                                |
| 30-day auto-revert                         | Active                                                                            | Active — *not relaxed*.                                                                                                                                                      |
| Detector promotion (shadow → live)         | One clinician proposes the review, second clinician promotes via feature-flag set | Single clinician sign-off **plus** server-enforced ≥48h gap between the most recent `shadow_mode_decision_reviewed` event for that gap and the `gap_*_enabled = true` flip. |
| Audit row                                  | `sole_clinician_override` field absent or `false`                                 | `sole_clinician_override: true` MUST appear in the `sensitive_bridge_log` event payload AND the auto-disable re-enable event payload.                                        |

### 13.2 Three conditions for assigning a clinician to `'sole_lead'`

The exemption is reserved for clinicians who satisfy **all three** of:

1. **Established therapeutic alliance.** The clinician has direct
   sustained therapeutic relationships with the survivors who would be
   affected by `safe_silence_mode` approvals on their account. The
   sole-clinician path skips the "second pair of eyes" safeguard, so the
   first pair must be well-calibrated to the population.

2. **External supervision exists.** A formal supervision relationship
   (peer-consultation group, external clinical supervisor, IRB
   oversight, or equivalent) is in place and is reviewing
   `sole_clinician_override` audit rows on at least a monthly cadence.
   The supervisor does not need IDP credentials in the sanctuary stack;
   their role is to read the audit trail out-of-band.

3. **Survivor informed consent.** Each affected survivor has received
   and acknowledged a written disclosure that this clinician operates
   in sole-lead mode, that approvals will be made by the same clinician
   who proposes them (in a separate session), and that the survivor may
   request transfer to a multi-clinician deployment at any time without
   penalty. Acknowledgement is captured in the survivor's record before
   the first `safe_silence_mode` proposal targeting them.

If any of (1)-(3) lapses, the lead clinician's row MUST be reverted to
`'multi_clinician_team'` via:

```sql
UPDATE coach_profiles
   SET clinician_authorization_type = 'multi_clinician_team',
       updated_at = NOW()
 WHERE username = 'CoachN';
```

Reversion takes effect on the next request — the lookup happens
per-request, no cache invalidation needed.

### 13.3 Audit & enforcement

* Migration 214 publishes the read-only view
  `v_clinician_authorization_mode` consumed by both the
  `sensitive_profile_api` two-step gate and the
  `sensitive_bridge_telemetry_api` feature-flag promotion endpoint.
* `SensitiveBridgeAuditor` runs two **folded** static-source checks
  (no new top-level slots; `_TOTAL_SLOTS` stays at 34):
  * `sole_clinician_session_separation_enforced` — folded into
    `safe_silence_state_view_present` (Tier 2).
  * `sole_clinician_reflection_delay_enforced` — folded into
    `shadow_mode_decision_review_current` (Tier 3).
  Either fold failing flips the parent slot to `ok=false`.
* Every sole-clinician approval emits `sole_clinician_override: true`
  inside the `additional_fields_redacted` payload of
  `sensitive_bridge_log` (event type `safe_silence_state_change`)
  and inside the `auto_disable_reenabled` payload for detector
  promotions. The supervisor in §13.2 (2) reviews these.
* The 48-hour reflection delay is calculated **server-side** from
  `MAX(skyeye_activity.created_at)` filtered by
  `type = 'shadow_mode_decision_reviewed'` and the actor or gap. Client
  clocks never enter the comparison.

### 13.4 Failure modes the exemption does NOT cover

* It does NOT permit single-session approval. Two distinct login
  sessions are still required.
* It does NOT remove the codeword precondition. A `sole_lead` clinician
  with zero active codewords on the target user receives the same
  `precondition_unmet` rejection.
* It does NOT remove the 30-day auto-revert.
* It does NOT extend to other admin operations (cohort exports, RBAC
  edits, retention-tier overrides). Those continue to follow whatever
  approval policy their respective subsystems define.

---

## 14. Runtime Log

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

2026-05-10T23:00:00Z [Migration 214] Sole-clinician deployment mode added.
  - Migration 214 created: clinician_authorization_type column on
    coach_profiles, default 'multi_clinician_team', CHECK constraint,
    partial index, v_clinician_authorization_mode view, CoachN backfill
    to 'sole_lead'.
  - sensitive_profile_api.py: safe_silence approve flow now reads the
    proposer's authorization type. sole_lead allows same-actor approval
    iff session hashes differ; multi_clinician_team enforces different
    actors. Audit row carries proposer_authorization_type and
    sole_clinician_override.
  - sensitive_bridge_telemetry_api.py: feature-flag promotion enforces
    server-side ≥48h reflection delay between shadow_mode_decision_reviewed
    and gap_*_enabled flip when actor is sole_lead. Audit row carries
    actor_authorization_type, sole_clinician_override, reviewed_at,
    reflection_delay_hours_required.
  - sensitive_bridge_auditor.py: two new static-source checks
    (sole_clinician_session_separation_enforced,
    sole_clinician_reflection_delay_enforced) folded into existing
    Tier-2 and Tier-3 slot details. _TOTAL_SLOTS unchanged at 34;
    no trust_baseline write required.
  - Playbook §13 (Sole-Clinician Deployment Mode) added documenting
    the deviation, the three conditions for assignment, and the
    audit/enforcement surface.

Future entries appended chronologically by the executing engineer.

# Agentic Roadmap Rollout Checklist (Phases 0–5)

**Status:** TRACK A + B BAKED ON STAGING, DUAL-REVIEWER SIGNED (2026-07-14) — migrations applied, Phase 0 + Phase 1 flipped/tested on `nate_staging_backend`, Flutter deployed, reviewed by Nathan Nevedal + Kristy Moore; audit token/accounts verified on GREEN. Production agentic flags **false**. **Not fully closed:** P3 (backup artifact was checking the wrong script's output — forensic re-check pending) and 0.4/1.4 (consent-default seam test now passes; shared-extractor isolation SQL check against staging still pending) — see inline notes. Prod flips (0.5/0.6/1.5) blocked on ≥72h staging soak (not started — soak clock begins at first prod Phase 0 flip) **and** the two pending checks above. Track C (Phase 5 neuro-symbolic) untouched.

**Infrastructure:** `docker-compose.staging.yml` + `scripts/staging_bake_setup.sh` → `nate_staging_backend` on `127.0.0.1:8011`, DB `little_nate_staging`. (Port 8001 is already bound by host nginx on GREEN for an unrelated vhost — do not reuse it.)

**Hard rules (from plan):**
- Apply migrations **237 → 238 → 239** on GREEN **before** any flag flip.
- **One phase per pass** — staging first, then production after verify.
- **Phase 0 flag must be on and stable** before `ENABLE_PROACTIVE_COMMITMENTS`.
- **Phase 5b** (`ENABLE_SYMBOLIC_VERIFIER`) gets the **deepest** adversarial review (clinical safety, regen cap, 988 append).
- **Phase 5d** (`ENABLE_CRYSTAL_GRAPH`) requires a **dedicated isolation audit** before its flag is ever flipped — separate from “going neuro-symbolic” as a whole.

**Deploy command (when ready):** `ssh root@68.183.168.75 "cd /opt/clinical-sovereignty-lab && git pull origin main && bash scripts/safe_deploy.sh <service>"`

---

## BLOCKER — Bake environment

**Resolved (2026-07-14):** Option **(a) Minimal bake on GREEN** — `docker-compose.staging.yml`, `little_nate_staging`, port **8011** (8001 was already in use by host nginx on GREEN).

```bash
ssh root@68.183.168.75 "cd /opt/clinical-sovereignty-lab && bash scripts/staging_bake_setup.sh"
bash scripts/staging_phase_flags.sh phase0 on   # staging only
bash scripts/staging_smoke_agentic.sh phase0
```

Production `:8000` / `nate_backend` agentic flags remain **false** until per-phase prod flip rows below.

---

## Pre-flight (once, before Phase 0 flag)

| Step | Action | Done |
|------|--------|------|
| P0 | CI green: `bash backend/scripts/run_ci_tests.sh` | [x] |
| P1 | Human sign-off: operator + second reviewer | [x] |
| P2 | `SKYEYE_AUDIT_TOKEN` + audit accounts on GREEN | [x] |
| P3 | Pre-migration backup verified — check **`daily_backup.sh`'s own output** (a timestamped dump under `/mnt/volume_sfo2_01/backups/daily/`), **not** `daily_vault_backup.sh`'s heartbeat file (different script, different artifact, only proves vault backups are running on schedule — not that a pre-migration snapshot exists) | [~] *(forensic check pending — see note)* |

**P3 forensic note (2026-07-14):** original P3 pass checked `.last_backup_heartbeat` (written by `daily_vault_backup.sh`, a *different* script covering only `Vaults/`). The actual pre-migration guarantee for migrations 237–239 depends on `daily_backup.sh` (full PG/Redis/app-data dump), which `staging_bake_setup.sh` calls immediately before applying migrations — but that specific run's output was never independently confirmed on disk. Run on GREEN to close:
```bash
ssh root@68.183.168.75 "ls -la /mnt/volume_sfo2_01/backups/daily/ | grep -i '2026.07.14\|2026-07-14'"
```
Looking for a dump timestamped near **13:22 UTC on 2026-07-14** (the `staging_bake_setup.sh` run that preceded migrations 237–239). Retrospective/non-blocking — migrations are additive DDL, already applied cleanly — but must be confirmed before this row reads `[x]`.

---

## Database migrations (GREEN — before any flag)

Run in order on `little_nate` (via `docker exec nate_postgres psql ...`):

| Migration | File | Done |
|-----------|------|------|
| 237 | `backend/migrations/237_proactive_touch_policy.sql` | [x] |
| 238 | `backend/migrations/238_nate_commitments.sql` | [x] |
| 239 | `backend/migrations/239_nate_therapeutic_plans.sql` | [x] |

Verify: `\d nate_proactive_touches`, `\d nate_commitments`, `\d nate_therapeutic_plans` (and related views/tables).

---

## Phase 0 — Proactive touch policy

**Flag:** `ENABLE_PROACTIVE_TOUCH_POLICY=false` (default)

| Step | Action | Done |
|------|--------|------|
| 0.1 | Adversarial walk: `docs/AGENTIC_PHASE_0_REVIEW.md` (key / lifecycle / surface / seam / time) | [x] |
| 0.2 | Seam tests: `test_proactive_touch_seams.py`, `test_touch_adaptation_asymmetry.py` | [x] |
| 0.3 | Staging: set flag `true`, restart backend | [x] |
| 0.4 | Verify: checkin touches route through `can_send_proactive_touch`; shadow table receives assertiveness proposals only | [~] *(partial — see note)* |
| 0.5 | Production flag flip (after 0.4 stable ≥ 72h) | [ ] |
| 0.6 | `safe_deploy.sh backend` + 117/117 health + trust window | [ ] |

**Blocks:** Phase 1 flag until 0.5 complete.

**0.4 partial-verification note (2026-07-14):** two gaps identified between "code review says it's safe" and "we watched it happen":
- **Consent default — closed.** `can_send_proactive_touch` denies (`skipped_consent`) when `profile_data.proactive_presence_consent` is absent (not just `False`) — confirmed by a fixture with the key entirely missing. New seam test `test_consent_never_set_denies` in `backend/tests/test_proactive_touch_seams.py` locks this in so a future refactor can't silently flip it to default-allow.
- **Shared-extractor isolation — open.** `nate_commitment_extractor.py` is shared between Phase 1 and Phase 5a; code confirms `symbols` is only added when `ENABLE_SYMBOLIC_EXTRACTION=true`, but this hasn't been confirmed under real staging traffic. Run on GREEN (Phase 1 has already exercised the extractor on staging with the flag false):
  ```bash
  ssh root@68.183.168.75 "docker exec nate_postgres psql -U nate_admin -d little_nate_staging -c \"SELECT count(*) FROM conversation_history WHERE metadata ? 'symbols' AND created_at > '2026-07-14 15:27:00 UTC';\""
  ```
  (`2026-07-14 15:27:00 UTC` = commit `6485305` 11:27:38 EDT, the last staging-infra fix before the Phase 1 flag flip / smoke test ran — a safe lower bound since the flag-flip itself isn't a git event. If you know the exact `staging_phase_flags.sh phase1 on` invocation time, use that instead.) **Zero** closes this row to `[x]`. Non-zero is a same-severity finding as a flag that's supposed to isolate Track C but doesn't — treat as a blocker, not a footnote.

---

## Phase 1 — Proactive commitments

**Flag:** `ENABLE_PROACTIVE_COMMITMENTS=false` (default)

| Step | Action | Done |
|------|--------|------|
| 1.1 | Confirm Phase 0 flag on and stable in prod | [ ] *(intentionally skipped — Track B ran on staging only, per two-track plan; prod Phase 0 not yet flipped)* |
| 1.2 | Adversarial walk: `docs/AGENTIC_PHASE_1_REVIEW.md` | [x] |
| 1.3 | Staging: flag `true`; test consent toggle, list/dismiss/edit commitments (WS + Flutter) | [x] |
| 1.4 | Verify: `NateCommitmentAgent` touches pass Phase 0 gate; `nate_nudges` delivery | [~] *(partial — see note)* |
| 1.5 | Production flag flip | [ ] |
| 1.6 | Flutter web deploy if UI changed (`scripts/deploy_flutter_web.sh`) | [x] |

**1.4 partial-verification note:** same two gaps as 0.4 above (`NateCommitmentAgent` touches route through the same `can_send_proactive_touch` gate and the same `nate_commitment_extractor.py`). Consent-default closed via `test_consent_never_set_denies`; extractor-isolation SQL check against staging `conversation_history` still pending — see 0.4 note for the exact query.

---

## Phase 2 — Tool executor

**Flag:** `ENABLE_NATE_TOOL_EXECUTOR=false` (default)

| Step | Action | Done |
|------|--------|------|
| 2.1 | Confirm Phase 1 stable | [ ] |
| 2.2 | Adversarial walk: `docs/AGENTIC_PHASE_2_REVIEW.md` | [ ] |
| 2.3 | Staging: propose/confirm book_session + set_reminder; no execution without explicit confirm | [ ] |
| 2.4 | Production flag flip | [ ] |
| 2.5 | `safe_deploy.sh bridge` if bridge hooks changed | [ ] |

---

## Phase 3 — Therapeutic plans

**Flag:** `ENABLE_THERAPEUTIC_PLANS=false` (default)

| Step | Action | Done |
|------|--------|------|
| 3.1 | Adversarial walk: `docs/AGENTIC_PHASE_3_REVIEW.md` | [ ] |
| 3.2 | Staging: coach REST assign/advance; client chat receives plan context block only | [ ] |
| 3.3 | Production flag flip | [ ] |

*May run on a parallel track to Phase 2, but still one flag per pass.*

---

## Phase 4 — Self-monitor

**Flags:** `ENABLE_SELF_MONITOR_AGENT`, `ENABLE_SELF_MONITOR_COACH_ALERT`, `ENABLE_SELF_MONITOR_TOUCH` (all default false)

| Step | Action | Done |
|------|--------|------|
| 4.1 | Discovery doc reviewed: `docs/AGENTIC_PHASE4_DISCOVERY.md` | [ ] |
| 4.2 | Adversarial walk: `docs/AGENTIC_PHASE_4_REVIEW.md` | [ ] |
| 4.3 | Staging: enable **coach alert only** first (`ENABLE_SELF_MONITOR_COACH_ALERT`) | [ ] |
| 4.4 | Optional client touch (`ENABLE_SELF_MONITOR_TOUCH`) only after Phase 0+1 proven | [ ] |
| 4.5 | Production flip per flag, separately | [ ] |

---

## Phase 5a — Symbolic extraction

**Flag:** `ENABLE_SYMBOLIC_EXTRACTION=false` (default)

| Step | Action | Done |
|------|--------|------|
| 5a.1 | Phase 0+1 flag-stable | [ ] |
| 5a.2 | Adversarial walk: `docs/AGENTIC_PHASE_5A_REVIEW.md` | [ ] |
| 5a.3 | Seam tests: `test_symbolic_extraction_seams.py` | [ ] |
| 5a.4 | Staging flip → verify `conversation_history.metadata.symbols` | [ ] |
| 5a.5 | Production flip | [ ] |

---

## Phase 5b — Symbolic verifier (deepest review)

**Flag:** `ENABLE_SYMBOLIC_VERIFIER=false` (default)

> **Do not rush.** This layer can regenerate clinical replies and append crisis resources. Requires the longest adversarial walk and operator clinical sign-off.

| Step | Action | Done |
|------|--------|------|
| 5b.1 | Phase 5a on and stable | [ ] |
| 5b.2 | **Deep adversarial walk:** `docs/AGENTIC_PHASE_5B_REVIEW.md` (distress+proud, 988, regen cap, crisis exempt) | [ ] |
| 5b.3 | Seam tests: `test_symbolic_verifier_seams.py` | [ ] |
| 5b.4 | Staging: verify `sse_therapeutic_audit_log` + `skyeye_activity` type `symbolic_verifier_action` | [ ] |
| 5b.5 | Production flip only after 5b.2 signed by **two humans** | [ ] |

---

## Phase 5c — Forward reasoning

**Flag:** `ENABLE_FORWARD_REASONING=false` (default)

| Step | Action | Done |
|------|--------|------|
| 5c.1 | Phase 5b on and stable | [ ] |
| 5c.2 | Adversarial walk: `docs/AGENTIC_PHASE_5C_REVIEW.md` | [ ] |
| 5c.3 | Seam tests: `test_forward_reasoning_seams.py` | [ ] |
| 5c.4 | Staging → production flip | [ ] |

---

## Phase 5d — Crystal graph (isolation audit required)

**Flag:** `ENABLE_CRYSTAL_GRAPH=false` (default)

> **Separate gate:** Run read-only isolation report (`crystal_graph_isolation.py`) and document cross-boundary findings **before** any flip. Phi auditor graph scan is tied to this same flag.

| Step | Action | Done |
|------|--------|------|
| 5d.1 | **Isolation audit** complete (read-only traversal report, no flag flip) | [ ] |
| 5d.2 | Adversarial walk: `docs/AGENTIC_PHASE_5D_REVIEW.md` | [ ] |
| 5d.3 | Seam tests: `test_crystal_graph_isolation_seams.py` | [ ] |
| 5d.4 | Staging flip only; verify phi auditor graph-surfaced scan + scope enforcement | [ ] |
| 5d.5 | Production flip — **last** Phase 5 flag | [ ] |

---

## Post-deploy verification (every phase)

- [ ] `docker logs nate_backend --since 2m | grep 'STARTUP COMPLETE'` → 117/117 (or current denominator)
- [ ] Bridge PG connected (`UserStore ready` in bridge logs)
- [ ] `ENVIRONMENT=production` on backend **and** bridge
- [ ] Trust enforcer window (optional): 580/580 after audit hour
- [ ] E2E smoke: real UI path for the phase (not linter-only)

---

## Reference

- Wiring inventory: `docs/AGENTIC_WIRING_INVENTORY.md`
- Plan (read-only): `.cursor/plans/little_nate_agentic_roadmap_ef224a28.plan.md`
- Flag defaults: `backend/app/config/_settings.py`, `.env.template`

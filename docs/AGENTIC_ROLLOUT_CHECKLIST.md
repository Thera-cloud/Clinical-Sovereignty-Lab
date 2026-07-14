# Agentic Roadmap Rollout Checklist (Phases 0–5)

**Status:** TRACK A IN PROGRESS — staging bake scripts on `main`; production agentic flags **false**. Run `staging_bake_setup.sh` on GREEN to apply migrations **237–239** and bring up `little_nate_staging`.

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
| P0 | CI green: `bash backend/scripts/run_ci_tests.sh` | [ ] |
| P1 | Human sign-off: operator + second reviewer | [ ] |
| P2 | `SKYEYE_AUDIT_TOKEN` + audit accounts on GREEN | [ ] |
| P3 | Backup / vault heartbeat < 48h (see `vault-backup-heartbeat.mdc`) | [ ] |

---

## Database migrations (GREEN — before any flag)

Run in order on `little_nate` (via `docker exec nate_postgres psql ...`):

| Migration | File | Done |
|-----------|------|------|
| 237 | `backend/migrations/237_proactive_touch_policy.sql` | [ ] |
| 238 | `backend/migrations/238_nate_commitments.sql` | [ ] |
| 239 | `backend/migrations/239_nate_therapeutic_plans.sql` | [ ] |

Verify: `\d nate_proactive_touches`, `\d nate_commitments`, `\d nate_therapeutic_plans` (and related views/tables).

---

## Phase 0 — Proactive touch policy

**Flag:** `ENABLE_PROACTIVE_TOUCH_POLICY=false` (default)

| Step | Action | Done |
|------|--------|------|
| 0.1 | Adversarial walk: `docs/AGENTIC_PHASE_0_REVIEW.md` (key / lifecycle / surface / seam / time) | [ ] |
| 0.2 | Seam tests: `test_proactive_touch_seams.py`, `test_touch_adaptation_asymmetry.py` | [ ] |
| 0.3 | Staging: set flag `true`, restart backend | [ ] |
| 0.4 | Verify: checkin touches route through `can_send_proactive_touch`; shadow table receives assertiveness proposals only | [ ] |
| 0.5 | Production flag flip (after 0.4 stable ≥ 72h) | [ ] |
| 0.6 | `safe_deploy.sh backend` + 117/117 health + trust window | [ ] |

**Blocks:** Phase 1 flag until 0.5 complete.

---

## Phase 1 — Proactive commitments

**Flag:** `ENABLE_PROACTIVE_COMMITMENTS=false` (default)

| Step | Action | Done |
|------|--------|------|
| 1.1 | Confirm Phase 0 flag on and stable in prod | [ ] |
| 1.2 | Adversarial walk: `docs/AGENTIC_PHASE_1_REVIEW.md` | [ ] |
| 1.3 | Staging: flag `true`; test consent toggle, list/dismiss/edit commitments (WS + Flutter) | [ ] |
| 1.4 | Verify: `NateCommitmentAgent` touches pass Phase 0 gate; `nate_nudges` delivery | [ ] |
| 1.5 | Production flag flip | [ ] |
| 1.6 | Flutter web deploy if UI changed (`scripts/deploy_flutter_web.sh`) | [ ] |

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

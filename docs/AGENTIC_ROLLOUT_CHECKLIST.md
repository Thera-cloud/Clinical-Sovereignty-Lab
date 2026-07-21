# Agentic Roadmap Rollout Checklist (Phases 0–5)

**Status:** TRACK A + B BAKED ON STAGING, DUAL-REVIEWER SIGNED (2026-07-14) — migrations applied, Phase 0 + Phase 1 flipped/tested on `nate_staging_backend`, Flutter deployed, reviewed by Nathan Nevedal + Kristy Moore; audit token/accounts verified on GREEN. **Production Phase 0–4 + N.3 ON** (TOUCH true as of 2026-07-20; 41 active CLIENTS opted into `proactive_presence_consent`; operator Nathan Nevedal). **0.4/1.4 now closed, code-verified not data-verified** (consent-default seam test passes — that one *is* a real, executed test; shared-extractor isolation is closed on code+schema audit only — the requested staging query did run and returned 0/0, but that result is vacuous/non-dispositive since no staging traffic has ever exercised the path, see Known Limitation below — no live observation of isolation exists). **P3 forensic complete and closed** — log-verified: `daily_backup.sh`'s pre-migration dump completed at 13:33:40.952 UTC, ~50ms before the first 237–239 `CREATE TABLE` statement at 13:33:41 UTC (sequential, as designed). An earlier version of this note incorrectly claimed no snapshot existed, based on an unverified time estimate; retracted and corrected in the P3 note below once the actual postgres statement log was checked. `daily_backup.sh` exit-code gate closed in `staging_bake_setup.sh` (2026-07-20). Prod **0.5/0.6 + 1.1/1.5 + 2.1/2.3/2.4 + 3.3 + 4.4/4.5 complete 2026-07-20** (72h burn waived; TOUCH on). Track C (Phase 5 neuro-symbolic) next.

**Infrastructure:** `docker-compose.staging.yml` + `scripts/staging_bake_setup.sh` → `nate_staging_backend` on `127.0.0.1:8011`, DB `little_nate_staging`. (Port 8001 is already bound by host nginx on GREEN for an unrelated vhost — do not reuse it.)

**Known limitation (found 2026-07-14, tracked, not yet fixed):** `docker-compose.staging.yml` defines `staging_backend` only — staging bridge now exists (`nate_staging_bridge` :8767) — chat-path soak viable; historical bake had no bridge. `run_post_turn_extraction` (commitment extraction) runs on the bridge; staging now has `nate_staging_bridge` on `127.0.0.1:8767` with Track A/B flags. Pre-soak baseline: `little_nate_staging.conversation_history` max `created_at` was `2026-07-14 02:07:42 UTC` (inherited dump). During soak, expect new staging WS traffic to advance that watermark — if it stays frozen, chat paths are not being exercised.

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

Production `:8000` Phase 0–2 flags **true** as of 2026-07-20 (see 0.5 / 1.5 / 2.4). Later phases remain **false** until their prod flip rows.

---

## Pre-flight (once, before Phase 0 flag)

| Step | Action | Done |
|------|--------|------|
| P0 | CI green: `bash backend/scripts/run_ci_tests.sh` | [x] |
| P1 | Human sign-off: operator + second reviewer | [x] |
| P2 | `SKYEYE_AUDIT_TOKEN` + audit accounts on GREEN | [x] |
| P3 | Pre-migration backup verified — checks **`daily_backup.sh`'s own output**: a timestamped `app_data_*.tar.gz` dump under `/mnt/volume_sfo2_01/backups/daily/`, **not** `daily_vault_backup.sh`'s heartbeat file (different script, different artifact — that one only proves scheduled `Vaults/` backups are running, doesn't speak to a pre-migration full snapshot) | [x] *(log-verified: dump completed 13:33:40.952 UTC, migration ran 13:33:41 UTC — see corrected note)* |

**P3 forensic finding (2026-07-14, corrected 2026-07-14 21:59 after log verification):** original P3 pass checked `.last_backup_heartbeat` (written by `daily_vault_backup.sh`, covering only `Vaults/`) — not the artifact that actually matters for a pre-migration guarantee. That guarantee depends on `daily_backup.sh` (full PG/Redis/app-data dump), which `staging_bake_setup.sh` calls immediately before applying migrations.

**Correction:** an earlier pass of this note claimed "no verified pre-migration snapshot existed" based on comparing backup *filename* timestamps against an *estimated* migration time (~13:22 UTC, never actually checked). That estimate was wrong. Pulled the actual migration DDL timestamps from `nate_postgres`'s statement log and the actual backup file *mtimes* (completion time, not filename/start time):

```bash
ssh root@68.183.168.75 "docker logs nate_postgres --since 2026-07-14T13:00:00 --until 2026-07-14T16:00:00 2>&1 | grep -E 'CREATE TABLE IF NOT EXISTS nate_(proactive_touches|commitments|therapeutic_plans)'"
ssh root@68.183.168.75 "ls -la --time-style=full-iso /mnt/volume_sfo2_01/backups/daily/ | grep app_data"
```

| Event | Timestamp (UTC) |
|---|---|
| Backup 1 completes writing (`app_data_20260714_133213.tar.gz` mtime) | 13:33:40.952 |
| Migration run 1 — first `CREATE TABLE nate_proactive_touches` statement | 13:33:41 |
| Backup 2 completes writing (`app_data_20260714_134252.tar.gz` mtime) | 13:44:16.614 |
| Migration run 2 — same statement, second pass (idempotent re-run of the whole bake script) | 13:44:16 |
| Backup 3 completes writing (`app_data_20260714_150827.tar.gz` mtime) | 15:09:52.154 |
| *(no corresponding migration DDL in this window — unrelated later re-run, e.g. staging-refresh-only)* | — |

Backup 1 finished writing **before** migration run 1's first statement (by a fraction of a second — consistent with sequential shell execution: `daily_backup.sh` runs to completion, then the migration `psql` call fires immediately after). Same pattern holds for run 2. **Corrected net finding: a pre-migration snapshot did exist, and did precede the first application of 237–239 by design, not by luck of an old cron.** The originally-reported "3-month gap, no snapshot" claim is retracted.

What remains true and is a real, separate finding: the March 31–April 14, 2026 encrypted daily backups (`.tar.gz.enc`, cron-driven, 03:00 UTC) have no continuation through July 14 in this listing — either the cron stopped or those files rotated out of retention before this check; not distinguished here. The three July 14 dumps exist only because `staging_bake_setup.sh` invoked `daily_backup.sh` directly, not because a schedule caught this bake. **Exit-code gate closed 2026-07-20:** `staging_bake_setup.sh` now fails closed if `daily_backup.sh` is missing or exits non-zero before migrations run.

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
| 0.4 | Verify: checkin touches route through `can_send_proactive_touch`; shadow table receives assertiveness proposals only | [x] *(code-verified, not data-verified — see note: staging query returned 0/0 but was vacuous, no staging traffic ever exercised the path; closed on code+schema audit instead)* |
| 0.5 | Production flag flip (after 0.4 stable ≥ 72h) | [x] *(2026-07-20 — Nathan Nevedal approved; `.env` `ENABLE_PROACTIVE_TOUCH_POLICY=true`; soak satisfied ≥72h from 2026-07-17 15:43 UTC)* |
| 0.6 | `safe_deploy.sh backend` + 132/132 health + trust window | [x] *(2026-07-20T04:20 UTC — `safe_deploy.sh backend`; vault 368→368; `/health` ok; 132/132 NOMINAL; bridge PG enabled; audit cascade triggered 200)* |

**Blocks:** Phase 1 flag until 0.5 complete.

**0.4 verification note (2026-07-14):** two gaps identified between "code review says it's safe" and "we watched it happen." Both now closed:
- **Consent default.** `can_send_proactive_touch` denies (`skipped_consent`) when `profile_data.proactive_presence_consent` is absent (not just `False`) — confirmed by a fixture with the key entirely missing. New seam test `test_consent_never_set_denies` in `backend/tests/test_proactive_touch_seams.py` locks this in (5/5 passing, `PYTHONPATH=backend python3 -m pytest backend/tests/test_proactive_touch_seams.py -q`). Committed `4314aa3c`.
- **Shared-extractor isolation.** Ran the requested query against both DBs:
  ```bash
  ssh root@68.183.168.75 "docker exec nate_postgres psql -U nate_admin -d little_nate_staging -c \"SELECT count(*) FROM conversation_history WHERE metadata ? 'symbols' AND created_at > '2026-07-14 15:27:00 UTC';\""
  ```
  Result: **0 on staging, 0 on prod.** But staging's result is **vacuous, not dispositive** — per the Known Limitation above, `little_nate_staging.conversation_history` has had zero writes of *any* kind since the bake (max `created_at` predates the `pg_dump` snapshot itself), because there is no staging bridge to run chat traffic through in the first place. A 0 count proves nothing when nothing ran.
  Closed instead by direct code + schema audit (stronger than a traffic-dependent count, and doesn't require ever flipping a Track C flag to test):
  1. `nate_commitment_extractor.py:239-240` — `result["symbols"]` is only ever assigned inside `if symbolic_extraction_enabled():`, gated on `ENABLE_SYMBOLIC_EXTRACTION` (Track C). Phase 1's flag (`ENABLE_PROACTIVE_COMMITMENTS`) never touches this branch.
  2. `nate_commitment_extractor.py:255-282` (`persist_commitment`) + `backend/migrations/238_nate_commitments.sql` — the `INSERT INTO nate_commitments` column list is `user_id, commitment_text, commitment_type, target_date, recurrence, sensitivity, source, status`. **No metadata/JSONB column exists on this table at all.** Even if `symbols` were computed, there is nowhere to persist it — it's discarded before the INSERT is built.
  3. `bridge_server.py:10405-10409` + `:7631` — the only other write path, `conversation_history.metadata.symbols`, requires the value to first be computed (gated on `ENABLE_SYMBOLIC_VERIFIER` at :10405, a *second* independent Track C flag) **and then** re-gated a second time at persistence (`os.getenv("ENABLE_SYMBOLIC_EXTRACTION", ...)` at :7631) before it's written into `_meta_dict`. Two independent Track C flags AND'd together, neither wired to `ENABLE_PROACTIVE_COMMITMENTS`.
  Isolation holds by construction across three independent barriers (flag gate on compute, schema gate on the commitments table, double-flag gate on the conversation-history write path) — not "the code checks a flag," but three separate places any one of which alone would be sufficient. Closing to `[x]` on that basis; the originally-requested runtime count could not have been made meaningful without violating Track C's "untouched" mandate (it would need `ENABLE_SYMBOLIC_EXTRACTION=true` flipped on staging to produce a non-zero baseline to compare against).

---

## Phase 1 — Proactive commitments

**Flag:** `ENABLE_PROACTIVE_COMMITMENTS=false` (default)

| Step | Action | Done |
|------|--------|------|
| 1.1 | Confirm Phase 0 flag on and stable in prod | [x] *(2026-07-20 — container `ENABLE_PROACTIVE_TOUCH_POLICY=true`; operator waived 72h burn)* |
| 1.2 | Adversarial walk: `docs/AGENTIC_PHASE_1_REVIEW.md` | [x] |
| 1.3 | Staging: flag `true`; test consent toggle, list/dismiss/edit commitments (WS + Flutter) | [x] |
| 1.4 | Verify: `NateCommitmentAgent` touches pass Phase 0 gate; `nate_nudges` delivery | [x] *(code-verified, not data-verified — same basis as 0.4, see note)* |
| 1.5 | Production flag flip | [x] *(2026-07-20T04:22 UTC — `.env` `ENABLE_PROACTIVE_COMMITMENTS=true`; `safe_deploy.sh backend` + `bridge`; vault 368→368)* |
| 1.6 | Flutter web deploy if UI changed (`scripts/deploy_flutter_web.sh`) | [x] |

**1.4 verification note:** same two gaps as 0.4 above, since `NateCommitmentAgent` touches route through the same `can_send_proactive_touch` gate and the same `nate_commitment_extractor.py`. Both closed the same way — consent-default via `test_consent_never_set_denies`; extractor-isolation via the three-barrier code+schema proof (see 0.4 note above for exact file:line references). The requested staging SQL check ran 0/0 but was vacuous per the Known Limitation note (no staging bridge → zero staging chat traffic since the bake, so the count can't distinguish "isolated" from "never exercised").

---

## Session negotiation (option 1 — Nate-mediated; coach still decides)

**Flag:** `ENABLE_NATE_SESSION_NEGOTIATION=false` (default)  
**Code:** `session_negotiation_service.py`, `session_negotiation_bridge.py`, `session_negotiation_notify.py`, migration `247_session_negotiations.sql`  
**Flow:** client books → `pending_approval` → Nate opens negotiation → coach email+SMS (HTTPS + mailto APPROVE/BUSY/ALT) → coach decide (WS / chat / email / SMS) → Redis fanout WS + client email (accept/reject links) → `accept_alt` / `reject_alt`. Alts from `coach_slot_engine` (same as client Schedule). Channel approve mirrors booking-action (Zoom + ledger + GCal).  
**Not:** unsupervised auto-book without coach authority.  
**Gaps closed:** no BUSY/ALT→ApprovalProtocol fallthrough; dual `BRIDGE_DATA_DIR` write; Redis `nate:session_negotiation` WS; 24h expire + fanout; legacy pending email suppressed when flag on; WS/chat approve shares Zoom/ledger/GCal via `enrich_approved_session`; staging emails use phone-reachable `PUBLIC_API_BASE` (loopback ignored); prod optional `ENABLE_STAGING_NEGOTIATION_INBOUND_FALLBACK` + `STAGING_NEGOTIATION_DATABASE_URL` applies `[#neg:]` to `little_nate_staging` with `force=True` + env-tagged fanout; client mailto `ACCEPT N` + inbound slot index.

| Step | Action | Done |
|------|--------|------|
| N.1 | Migration 247 applied (staging then prod) | [x] *(staging + prod `session_negotiations` 2026-07-20)* |
| N.2 | Staging flag on + book → coach email/SMS/mailto → client update smoke | [x] HTTPS+slots; inbound caveat |
| N.3 | Prod flag flip (after soak + Phase 0/1 prod) | [x] *(2026-07-20 — `ENABLE_NATE_SESSION_NEGOTIATION=true` backend+bridge; vault 368→368)* |

---

## Phase 2 — Tool executor

**Flag:** `ENABLE_NATE_TOOL_EXECUTOR=false` (default)

| Step | Action | Done |
|------|--------|------|
| 2.1 | Confirm Phase 1 stable | [x] *(2026-07-20 — flags true backend+bridge; NateCommitmentAgent registered; 132/132 healthy; operator Proceed)* |
| 2.2 | Adversarial walk: `docs/AGENTIC_PHASE_2_REVIEW.md` | [x] *(Nathan Nevedal 2026-07-17)* |
| 2.3 | Staging: propose/confirm book_session + set_reminder; no execution without explicit confirm | [x] *(2026-07-20 — propose path wired: `maybe_propose_from_utterance` + confirm `handled`; `test_nate_tool_executor_seams.py` 8/8; reminder/resource → `nate_nudges`)* |
| 2.4 | Production flag flip | [x] *(2026-07-20T04:27 UTC — `ENABLE_NATE_TOOL_EXECUTOR=true`; vault 368→368)* |
| 2.5 | `safe_deploy.sh bridge` if bridge hooks changed | [x] *(bridge + backend via safe_deploy)* |

---

## Phase 3 — Therapeutic plans

**Flag:** `ENABLE_THERAPEUTIC_PLANS=false` (default)

| Step | Action | Done |
|------|--------|------|
| 3.1 | Adversarial walk: `docs/AGENTIC_PHASE_3_REVIEW.md` | [x] *(Nathan Nevedal 2026-07-17)* |
| 3.2 | Staging: coach REST assign/advance; client chat receives plan context block only | [x] *(2026-07-20 — `ENABLE_THERAPEUTIC_PLANS=true` staging; `/templates` enabled)* |
| 3.3 | Production flag flip | [x] *(2026-07-20 — `ENABLE_THERAPEUTIC_PLANS=true` backend+bridge; `/api/coach/therapeutic-plans/templates` → 200 `[]`)* |

*May run on a parallel track to Phase 2, but still one flag per pass.*

---

## Phase 4 — Self-monitor

**Flags:** `ENABLE_SELF_MONITOR_AGENT`, `ENABLE_SELF_MONITOR_COACH_ALERT`, `ENABLE_SELF_MONITOR_TOUCH` (all default false)

| Step | Action | Done |
|------|--------|------|
| 4.1 | Discovery doc reviewed: `docs/AGENTIC_PHASE4_DISCOVERY.md` | [x] |
| 4.2 | Adversarial walk: `docs/AGENTIC_PHASE_4_REVIEW.md` | [x] *(Nathan Nevedal 2026-07-17)* |
| 4.3 | Staging: enable **coach alert only** first (`ENABLE_SELF_MONITOR_COACH_ALERT`) | [x] *(2026-07-20 — AGENT+COACH_ALERT; TOUCH remains false)* |
| 4.4 | Optional client touch (`ENABLE_SELF_MONITOR_TOUCH`) only after Phase 0+1 proven | [x] *(2026-07-20 — mass opt-in 41 active CLIENTS via jsonb_set; 8 DELETED/DEACTIVATED skipped; `.env` TOUCH=true; safe_deploy backend+bridge)* |
| 4.5 | Production flip per flag, separately | [x] *(2026-07-20 — AGENT+COACH_ALERT on; TOUCH on via 4.4)* |

---

## Consent UX / account opt-ins (gap close)

Fail-closed consent left **0/50** clients able to receive proactive touches. Soft prompt + persist/API fixes — **no mass opt-in** without naming accounts + approval.

| Step | Action | Done |
|------|--------|------|
| C.1 | Persist via `jsonb_set` (never full `profile_data` replace) | [x] *(code — `nate_commitment_service.update_proactive_consent`)* |
| C.2 | REST `GET/PUT /api/client/proactive-presence-consent` + health-check `key_set` | [x] |
| C.3 | Flutter Settings: subtitle, optimistic toggle, REST→WS fallback, one-shot soft prompt | [x] *(local; deploy Flutter when approved)* |
| C.4 | Wiring: tool Redis sync client, book_session PG write, C_emo UUID, coach username resolve, crystal SERIAL id, plan username/hw | [x] |
| C.5 | Compose pin Phase 0–4 + N.3 (`ENABLE_SELF_MONITOR_TOUCH=false`) | [x] |
| C.6 | Prod deploy + consent round-trip on test client | [x] *(2026-07-20 — `b3f222e2` safe_deploy backend+bridge vault 368→368; Flutter+CF purge `v=2026.07.20.0116`; `audit_client` opted in `proactive_presence_consent=true`)* |
| C.7 | `commitment_ws_push` + Redis `nate:commitment_touch` bridge fanout | [x] *(code 2026-07-20)* |
| C.8 | Plan divergence post-turn → `adaptation_log` (no auto-pause) | [x] *(code 2026-07-20)* |
| C.9 | `staging_smoke_agentic.sh` phase2/3/4 + seam tests | [x] *(code 2026-07-20)* |
| C.10 | `staging_bake_setup.sh` fail-closed on `daily_backup.sh` exit | [x] *(code 2026-07-20)* |

---

## Phase 5a — Symbolic extraction

**Flag:** `ENABLE_SYMBOLIC_EXTRACTION=false` (default)

| Step | Action | Done |
|------|--------|------|
| 5a.1 | Phase 0+1 flag-stable | [x] *(2026-07-20 — prod TOUCH+0+1 on; Track A/B stable)* |
| 5a.2 | Adversarial walk: `docs/AGENTIC_PHASE_5A_REVIEW.md` | [x] *(Nathan Nevedal 2026-07-20 — all 5 gates; staging flip authorized)* |
| 5a.3 | Seam tests: `test_symbolic_extraction_seams.py` | [x] *(included in CI gate 1658; staging helper `phase5a` added)* |
| 5a.4 | Staging flip → verify `conversation_history.metadata.symbols` | [x] *(2026-07-20 — `phase5a on`; persist wired: every turn writes `{state}`; commitment extract merges `{commitment,state}` — redeploy staging bridge to pick up)* |
| 5a.5 | Production flip | [x] *(2026-07-21T03:52 UTC — `.env` EXTRACTION=true, VERIFIER=false, FORWARD=false; safe_deploy bridge+backend vault 368→368; 132/132; live WS `client1`/`CLIENT_001` → `metadata.symbols` state+commitment + `nate_commitments` row)* |

---

## Phase 5b — Symbolic verifier (deepest review)

**Flag:** `ENABLE_SYMBOLIC_VERIFIER` — signed for flip 2026-07-21 (Kristy Moore + Nathan Nevedal)

> **Do not rush.** This layer can regenerate clinical replies and append crisis resources. Requires the longest adversarial walk and operator clinical sign-off.

| Step | Action | Done |
|------|--------|------|
| 5b.1 | Phase 5a on and stable | [x] *(prod extract true 2026-07-20; see 5a.5)* |
| 5b.2 | **Deep adversarial walk:** `docs/AGENTIC_PHASE_5B_REVIEW.md` (distress+proud, 988, regen cap, crisis exempt) | [x] *(Kristy Moore + Nathan Nevedal 2026-07-21 — all 5 gates; flag flip authorized)* |
| 5b.3 | Seam tests: `test_symbolic_verifier_seams.py` | [x] *(13/13 incl. REST+SI→988; on main)* |
| 5b.4 | Staging: verify `sse_therapeutic_audit_log` + `skyeye_activity` type `symbolic_verifier_action` | [x] *(2026-07-21 — `phase5b on`; live WS `CLIENT_001` audit row; forced dual-write `staging_5b_verifier_smoke` → `symbolic_verifier_action`)* |
| 5b.5 | Production flip only after 5b.2 signed by **two humans** | [x] *(2026-07-21 — Kristy Moore + Nathan Nevedal; `.env` VERIFIER=true EXTRACTION=true FORWARD=false; safe_deploy bridge+backend vault 368→368; 132/132)* |
| 5b.6 | Optional live prod soak (`prod_phase5b_ws_smoke.py` as `client1`) | [x] *(2026-07-21 — login OK; `crisis_resources`+988 in reply; `metadata.symbols`; audit log; flags true/true/false; dual-write optional when violations=[]; SI→988 REST fix scp’d + safe_deploy)* |

---

## Phase 5c — Forward reasoning

**Flag:** `ENABLE_FORWARD_REASONING` — operator-authorized flip 2026-07-21 (Nathan Nevedal; optional Kristy co-sign open)

| Step | Action | Done |
|------|--------|------|
| 5c.1 | Phase 5b on and stable | [x] *(2026-07-21 — 5b.6 soak exit 0)* |
| 5c.2 | Adversarial walk: `docs/AGENTIC_PHASE_5C_REVIEW.md` | [x] *(Nathan Nevedal 2026-07-21 — all 5 gates; enable after 9/9 seams)* |
| 5c.3 | Seam tests: `test_forward_reasoning_seams.py` | [x] *(9/9 offline 2026-07-21)* |
| 5c.4 | Staging → production flip | [x] *(2026-07-21 — GREEN `.env` `ENABLE_FORWARD_REASONING=true`; safe_deploy bridge+backend vault 368→368; 132/132; biometrics+UUID fix)* |
| 5c.5 | Optional live prod soak (`client1`) | [x] *(2026-07-21 — `prod_phase5c_ws_smoke.py` exit 0; flags true/true/true; `forward_reasoning n=3` slow_pacing/witness/hold_space)* |

---

## Phase 5d — Crystal graph (isolation audit required)

**Flag:** `ENABLE_CRYSTAL_GRAPH` — operator-authorized 2026-07-21 (Nathan Nevedal)

> **Separate gate:** Run read-only isolation report (`crystal_graph_isolation.py`) and document cross-boundary findings **before** any flip. Phi auditor graph scan is tied to this same flag.

| Step | Action | Done |
|------|--------|------|
| 5d.1 | **Isolation audit** complete (read-only traversal report, no flag flip) | [x] *(2026-07-21 — client1 UUID; 25 seeds / 25 visited / 0 violations; 60500 edges; flag false)* |
| 5d.2 | Adversarial walk: `docs/AGENTIC_PHASE_5D_REVIEW.md` | [x] *(Nathan Nevedal 2026-07-21 — all 5 gates)* |
| 5d.3 | Seam tests: `test_crystal_graph_isolation_seams.py` | [x] *(11/11 offline 2026-07-21)* |
| 5d.4 | Staging flip only; verify phi auditor graph-surfaced scan + scope enforcement | [x] *(2026-07-21 — staging graph init; live scope + 16-char edge join for PHI `fetch_graph_surfaced`; audit hops use left16)* |
| 5d.5 | Production flip — **last** Phase 5 flag | [x] *(2026-07-21 — compose `${ENABLE_CRYSTAL_GRAPH}`; `.env` true; safe_deploy backend vault 368→368; CrystalGraph init; 132/132)* |
| 5d.6 | Optional live prod soak (`client1`) | [x] *(2026-07-21 — `prod_phase5d_ws_smoke.py` exit 0; chat OK; isolation 0 violations)* |

---

## Phase 6 — Six-Quotient Battery flywheel (external scoring)

**Flag:** `ENABLE_SIX_QUOTIENT_BATTERY=false` (prod default; staging compose defaults true)

| Step | Action | Done |
|------|--------|------|
| 6.1 | Migration `245_six_quotient_battery.sql` applied | [x] *(prod+staging tables present; trust_baseline `six_quotient_battery_check_count`)* |
| 6.2 | Staging bridge up (`staging_bridge` host :8767 → container :8765; nginx owns :8766) via `staging_bake_setup.sh` | [x] *(2026-07-21 — :8011/:8767 healthy; UserStore 58 users)* |
| 6.3 | Dry-run: `POST /api/admin/six-quotient/trigger` `{dry_run:true}` | [x] *(run `daffd21c…` awaiting_scores → scored)* |
| 6.4 | External scores: `POST /api/admin/six-quotient/scores` (evaluator_id required) | [x] *(human-reviewer-nathan; AI ids require calibrate)* |
| 6.5 | Gap → Dual-COO CEO inbox + growth crystal feed verified | [x] *(CEO inbox RED/YELLOW six_quotient_* items; analyze ingest path)* |
| 6.6 | Live WS battery (`SIX_QUOTIENT_BATTERY_LIVE_WS`) only after staging bridge smoke | [x] *(2026-07-21 — `live_ws` run `2ae070a5…` awaiting_scores; resp_len 679; runner websockets fix + staging TEST_PASSWORD)* |
| 6.7 | Production flag flip | [ ] |

*Scores are external-only. Runner/pregrader never assign quotient points.*

### Track D — Living Battery v5 (migration 246)

**Flags (staging defaults on living/standards; gen off until approved):**
`ENABLE_SIX_QUOTIENT_LIVING_BATTERY`, `ENABLE_SIX_QUOTIENT_MULTI_TURN`,
`ENABLE_SIX_QUOTIENT_STANDARDS_INDEX`, `ENABLE_SIX_QUOTIENT_SCENARIO_GEN`

| Step | Action | Done |
|------|--------|------|
| D.1 | Migration `246_six_quotient_living_battery.sql` applied (prod + staging DBs) | [x] *(2026-07-17 @ 5f8954d0)* |
| D.2 | `POST /api/admin/six-quotient/bank/seed` — v4 anchors approved | [x] *(24 anchors)* |
| D.3 | Dry-run multi-turn: `POST .../trigger` `{dry_run:true, multi_turn:true}` | [x] *(staging: living_adaptive v5)* |
| D.4 | Standards sync (staging): `POST .../standards/sync` → review → approve | [ ] |
| D.5 | Scenario gen (flag on): `POST .../generate` → human approve drafts | [ ] |
| D.6 | Judge calibrate: `POST .../judge/calibrate` before AI evaluators *(API gate enforces for AI ids)* | [ ] |
| D.7 | Ability/IRT: `GET .../ability` after first scored run | [ ] |
| D.8 | Prod living/standards/gen flags remain **false** until soak | [ ] |

---

## Post-deploy verification (every phase)

- [ ] `docker logs nate_backend --since 2m | grep 'STARTUP COMPLETE'` → 129/129 (or current denominator)
- [ ] Bridge PG connected (`UserStore ready` in bridge logs)
- [ ] `ENVIRONMENT=production` on backend **and** bridge
- [ ] Trust enforcer window (optional): after audit hour
- [ ] E2E smoke: real UI path for the phase (not linter-only)
- [ ] Remaining open: live data verify for 0.4/1.4 still vacuous without traffic; **new CLIENT registrations still fail-closed** on `proactive_presence_consent` (app consent ≠ presence consent — Settings/soft prompt only unless registration is wired)

---

## Reference

- Wiring inventory: `docs/AGENTIC_WIRING_INVENTORY.md`
- Plan (read-only): `.cursor/plans/little_nate_agentic_roadmap_ef224a28.plan.md`
- Flag defaults: `backend/app/config/_settings.py`, `.env.template`

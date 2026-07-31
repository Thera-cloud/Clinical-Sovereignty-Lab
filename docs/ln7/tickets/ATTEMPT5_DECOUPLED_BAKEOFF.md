# ATTEMPT 5 AMENDMENT — Decoupled Bakeoff Architecture (supersedes Attempt 4 standard)
*(For review and filing into BAKEOFF_THREAD_PARKED_20260730.txt. This is a filed standard, not a launch authorization.)*

## Engineering status (BLUE — 2026-07-31)

| Gate | Status |
|------|--------|
| Amendment filed (`docs/ln7/tickets/` + `~/.local/state/ln7_gpu_watch/ATTEMPT5_AMENDMENT_20260731.txt`) | DONE |
| Mig 313 freeze/verdict tables | DONE (local; apply on GREEN before persist) |
| Phase B scorer + fixture CI (`test_ln7_decoupled_bakeoff.py`) | DONE — 6/6 pass |
| Phase A dry-run script (default; paid gated) | DONE — no GPU |
| Host-role + binary audit preflight | DONE — PASS |
| Live penny non-GPU droplet | PASS — droplet-scoped auth; id `588869818` create→destroy 404 (2026-07-31) |
| Paid Phase A GPU | **NOT AUTHORIZED** — organic G1 ≪ 300; `LN7_BURST_ALLOW_PAID` unset |

---

## Authorization

One attempt, executed as two decoupled phases. This amendment supersedes the Attempt 4 standard by absorbing it: all Attempt 4 preconditions (host-role contract, topology matrix, destroy self-test, binary audit) remain in force and become Phase A preflight items. There is no Attempt 6. The fail clause at the bottom is the final disposition path.

**Nothing in this amendment authorizes GPU spend.** The paid gate is unchanged:
`≥300 organic G1 rows AND reviewed host-contract patch on main AND LN7_BURST_ALLOW_PAID=1`

---

## Core architectural change (the lesson of seams 1–7)

**Decouple inference from scoring. Generate once, freeze, kill the droplet, score offline, re-score freely.**

All seven seams were scoring/plumbing defects. Every one cost a GPU re-provision to re-attempt because inference and scoring ran fused in a single pass. Under this standard, a scoring defect costs a free local re-run. The droplet's only job is token generation; its lifetime is minutes; scoring never holds a GPU hostage again.

---

## Phase A — Inference (paid, minutes, dies fast)

1. Provision droplet (host-role contract enforced; Attempt 4 preflights green first).
2. Load base + both arm adapters into vLLM; identity probe gate (distinct adapter_ok, as built).
3. **Generate all completions for all packs, both arms, in one batch.** No scoring on the droplet. No harness. No CI. Just generation.
4. **Freeze raw outputs to persistent storage** (R2 + Postgres row per completion):
   `{burst_id, prompt_hash, pack_id, task_id, arm_revision_id, adapter_sha, raw_text, gen_latency_ms, ts}`
5. Verify frozen-set completeness: row count == packs × tasks × arms; every row non-empty raw_text OR explicit generation-error reason (silent_empty banned at this layer too).
6. **Destroy droplet immediately** (destroy self-test path: delete → second poll → 404 confirmed; never ANOMALY-then-exit).

Total GPU exposure: generation time only. Target: under 30 minutes for 2 arms × 24 tasks.

## Phase B — Scoring (free, local, re-runnable forever)

Runs on GREEN (or anywhere) against the frozen set. Zero GPU. Repeatable without limit.

1. **Anchor control first:** a synthetic "arm" whose completions are ground-truth-correct diffs, injected into the frozen set at freeze time (Phase A step 4 writes it alongside the real arms). The evaluator scores the anchor before touching real arms.
   **Gate: anchor must score ~1.0.** Anchor scoring 0/NaN/null = evaluator plumbing broken = fix scorer, re-run Phase B. Real-arm results are unreadable until the anchor passes.
2. **5-row smoke assertion:** score 5 rows end-to-end → ledger. Assert valid, non-null numeric scores landed. Fail = stop, fix, re-run Phase B. The full pass must not run until the smoke rows are green.
3. **Full scoring pass:** diff extraction → sandbox CI apply/test → score per row → ledger write with arm attribution.
4. **Seam contracts, fail-fast:** strict schema between every stage (typed fields, required keys). Unexpected shape, None, NaN, or failed parse = immediate exception with stack trace. No silent completion with blank metrics — a crash at row 2 beats a clean run of nulls.
5. **Verdict:** only after anchor green + smoke green + full pass complete: means/lo/hi per arm, winner line, burst_id, both revision IDs → `bakeoff_verdict` in the ledger.

Any Phase B failure at any step: fix the scorer, re-run Phase B against the same frozen set. No droplet. No new amendment. Unlimited retries at $0 — this is the entire point.

---

## Preconditions (order; droplet last — Attempt 4 items absorbed)

1. This amendment reviewed and filed before any engineering claims completion against it.
2. Host-role contract on main with fence test (loopback assertion; seam-7 regression test).
3. Binary audit in preflight (timeout/jq/curl/python3/rsync/doctl per host, fail closed).
4. Topology matrix dry-run green ($0).
5. Destroy self-test green + one live penny-droplet rehearsal (provision cheapest non-GPU droplet, destroy via trap path, 404-poll confirmed; ~$0.01).
6. **Phase A/B split implemented and CI-tested:** freeze-write path unit-tested; Phase B runnable against a fixture frozen set (synthetic completions) with anchor + smoke gates passing in CI. Phase B must be proven on fixtures before Phase A ever runs.
7. Paid Phase A ONLY after: ≥300 organic G1 rows AND reviewed contract patch AND `LN7_BURST_ALLOW_PAID=1`. Engineering completion alone is NOT spend permission — starved-era adapters do not justify a droplet regardless of how good the instrument gets.

---

## Fail clause

- **Phase B failures are not attempt failures.** They are free scorer bugs, fixed and re-run without ceremony against the frozen set.
- **Phase A failure** (provision, serving, generation, freeze, or destroy path) after all preconditions were green → park. Re-entry requires a reviewed fix on main AND the rows condition re-confirmed. No Attempt 6. No debate. No stories.
- Any orphaned droplet from any path: destroy-verify to 404 is part of the disposition, never optional.

---

## What this buys (filed rationale)

- A seam 8, if it exists, costs a local re-run instead of a droplet night.
- "Bad model or broken meter?" is answered structurally by the anchor, in seconds, forever.
- Fake zeros cannot launch a full pass (smoke gate) and cannot complete one silently (fail-fast contracts).
- GPU spend collapses to generation-only minutes; every future bakeoff inherits the shape.
- The re-entry run, whenever the rows arrive, lands on an instrument whose scoring half was proven on fixtures in CI before a dollar moved.

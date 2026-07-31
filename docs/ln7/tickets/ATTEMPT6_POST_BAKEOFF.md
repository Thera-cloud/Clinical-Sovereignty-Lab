# Attempt 6 — Post-Bakeoff Operational Spec (executed)

**Date:** 2026-07-31  
**Winner (A/B):** `LN7-2026-07-30T190327Z` vs `LN7-2026-07-30T191329Z`  
**Burst:** `Attempt6`  
**PRE6:** bypass closed — future Phase A requires ≥300 organic G1 `ci_pack` rows **and** `LN7_BURST_ALLOW_PAID=1`.

## Activation math (CEO gate)

Require **strict dominance**: `candidate_ci.lo > incumbent_ci.hi` (non-overlapping CIs) over the expanded outcome set. Point-estimate `cand_lo > baseline_mean` is insufficient for sign-off.

## Artifacts

- Local: `~/.local/state/ln7_gpu_watch/frozen_Attempt6.jsonl`
- R2: `ln7/bakeoff/Attempt6/frozen_Attempt6.jsonl` (`R2_COLD_BUCKET`)
- Ledger: `ln7_bakeoff_verdicts` + `ln7_bakeoff_frozen_completions` (`burst_id=Attempt6`)
- Tag: `bakeoff-v0.6-attempt6-proven`

## G2

Untouched until separate CEO authorization after Step 0 green.

---

## Steps 6–8 (code-level spec — built)

| Step | Artifact | Status |
|------|----------|--------|
| 6.1 | `backend/tests/fixtures/attempt6_*` + `test_bakeoff_regression.py` (`pytest.approx`) | green offline |
| 6.2 | `scripts/ln7_attempt6_autopsy.py` → `docs/ln7/ATTEMPT6_AUTOPSY.md` | hypotheses only |
| 6.3 | mig `314` + `ln7_fuel_gauge.py` (slope via `days_tracked`) | code ready; apply 314 on GREEN |
| 6.4 | `ln7_serve_health_monitor.py` → `ln7_rollback.py` (`MIN_REQUEST_FLOOR=30`) | code ready |
| 7 | `ln7_bakeoff` bus + `LN7_BAKEOFF_DRY=1` acceptance | dry PASS |
| 8 | MemoryMax drop-in, DO audit, `INCIDENT_SEAMS_1_TO_7_CLOSED.md` | see STEP8 checklist |

Sharpenings applied: float `approx`, health N≥30, fuel slope ≠ blind `/7`.

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

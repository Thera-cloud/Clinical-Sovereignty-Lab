# Incident Closed — Scoring Seams 1–7 → Attempt 6 Proven Baseline

**STATUS:** CLOSED (operational). M2 adapter registry may later derive from this ledger.  
**Date closed:** 2026-07-31  
**Tag:** `bakeoff-v0.6-attempt6-proven`  
**Ledger commit (ops push):** `9d33147a` (pre–Steps 6–8); Steps 6–8 land separately.

---

## Root cause summary (seven seams → three dispositions)

| Disposition | Seams (abbrev.) | Fix class |
|-------------|-----------------|-----------|
| **Scorer / meter false** | Anchor identity, pack oracle mismatch, pass/fail vs partial-credit conflation, seam schema drift | Decoupled Phase B + frozen completions + CI gold lock (`test_bakeoff_regression.py`) |
| **Serve / host contract** | Inference fused with scoring (GPU held hostage), host-role confusion, destroy/404 gaps | Attempt 5/6 host contract + Phase A generate→freeze→destroy + 404 poll |
| **Promotion / fuel gates** | Premature paid burst, auto-promote without dominance, organic G1 undercount | PRE6 ≥300 trainable shadows; CEO hold; no G2 without explicit gate |

All seven were **scoring/plumbing** defects, not “Arm B is smarter.” Re-running fused GPU passes to re-score was the cost amplifier; Attempt 6 proved the split.

---

## Attempt 6 execution ledger (proof)

| Field | Value |
|-------|--------|
| Freeze | `frozen_Attempt6.jsonl` — 18 rows (12 real + 6 anchors) |
| R2 | `r2://nate-cold-archive/ln7/bakeoff/Attempt6/frozen_Attempt6.jsonl` |
| Arm A | `LN7-2026-07-30T190327Z` — mean ≈ **0.292** |
| Arm B | `LN7-2026-07-30T191329Z` — mean ≈ **0.167** |
| Winner | **Arm A** (`LN7-2026-07-30T190327Z`) |
| Anchor mean | **1.0** (meter true) |
| Postgres | `ln7_bakeoff_verdicts` + `ln7_bakeoff_frozen_completions` (mig 313) |
| CEO | **HOLD** — not promoted; `ENABLE_LN7_AUTO_PROMOTE=false` |
| Canary | `hold_shadow` (strict dominance not met vs fast incumbent) |

Gold fixture for CI: `backend/tests/fixtures/attempt6_gold_standard.jsonl`  
Expected scores: `backend/tests/fixtures/attempt6_expected_scores.json`

---

## Final baseline registration payload (M2 registry seed)

```json
{
  "baseline_id": "attempt6_proven_v0.6",
  "tag": "bakeoff-v0.6-attempt6-proven",
  "winner_revision": "LN7-2026-07-30T190327Z",
  "loser_revision": "LN7-2026-07-30T191329Z",
  "anchor_mean": 1.0,
  "mean_a": 0.292,
  "mean_b": 0.167,
  "n_real": 12,
  "n_anchor": 6,
  "promotion": "hold_shadow",
  "frozen_uri": "r2://nate-cold-archive/ln7/bakeoff/Attempt6/frozen_Attempt6.jsonl",
  "scorer_lock": "backend/tests/test_bakeoff_regression.py",
  "notes": "Do not curate training from n=12; wait fuel-era n>=50 (see ATTEMPT6_AUTOPSY.md)"
}
```

---

## Follow-on controls (Steps 6–8)

1. **CI regression** — Phase B must reproduce Attempt 6 per-task pass flags + means (`pytest.approx`).
2. **Fuel gauge** — nightly trainable counts → approach@240 / crossed@300 / stall@10d (mig 314).
3. **Serve health** — p99 + error-rate sensors feed **existing** rollback; `MIN_REQUEST_FLOOR=30`.
4. **Queens bus** — `ln7_bakeoff` dry path (`LN7_BAKEOFF_DRY=1`) proven; live requires `LN7_BURST_ALLOW_PAID=1` + PRE6.
5. **Housekeeping** — ORANGE PEFT MemoryMax, DO stray-droplet audit, this archive.

---

## Explicit non-claims

- Arm A win ≠ fast-tier activation.
- r16-beat-r32 (if observed in autopsy) = **hypothesis only** until n≥50.
- No auto-dispatch of paid bakeoff from fuel gauge — human sets paid flag + enqueue.

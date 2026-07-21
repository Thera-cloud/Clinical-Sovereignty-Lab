# Clinical AGI-Class → ASI Research Journey

**Status:** Operational path (not a marketing claim)  
**Updated:** 2026-07-21  
**Related:** `docs/AGENTIC_ROLLOUT_CHECKLIST.md` Track D.12–D.13, `docs/AGENTIC_WIRING_INVENTORY.md`

## Honesty rule (Tier 0)

- Never claim **AGI** or **ASI** from flag flips, crystal counts, or judge κ alone.
- Scoreboard = external six-quotient + human/clinician review + held-out transfer.
- ASI is a **research horizon** with containment — not a feature flag.

## Tier map

| Tier | Name | Goal | Prod gate |
|------|------|------|-----------|
| 0 | Clinical ANI | Neuro-symbolic + tools + battery scaffolding | Phases 0–5d + Phase 6 / Track D core — **done** |
| 1 | Clinical AGI-class | Transfer on held-out bank; live cues move θ; free-label calibration | D.12 nightly + D.13 accel + soak → then `SIX_QUOTIENT_WEEKLY_LIVE` |
| 2 | Narrow AGI | Same mind across therapy / family / DOJO / truth-bound ops | Cross-domain batteries + privacy walls |
| 3 | AGI | Open novel problems + gated self-improve | Sovereign train + formal verify |
| 4 | ASI | Superhuman recursive improve | Containment + society-scale eval — **not a ship date** |

## Clinical AGI-class exit criteria (Tier 1)

All must hold before any “clinical AGI-class” language:

1. **Nightly measure active** — `SIX_QUOTIENT_NIGHTLY_MEASURE=true`; `six_quotient_theta_trend` growing (nightly + Saturday transfer).
2. **Held-out transfer** — `bank_held_out ≥ 5`; transfer Δ logged; ability θ not updated from transfer runs.
3. **Acceleration channel** — `ENABLE_SIX_QUOTIENT_ACCELERATION=true`; cycle sweep writes predictions; Brier computable when `n_clients ≥ 5` (sparse OK until then).
4. **Weekly act gated** — `SIX_QUOTIENT_WEEKLY_LIVE=true` only after ≥7 nights of trend + human review of self-dev/CEO path.
5. **Crisis / hallu SLA** — no high-severity hallucination crystals in audit windows; crisis false-negative below clinical SLA.
6. **Gate script green** — `python3 backend/scripts/clinical_agi_class_gate_check.py` (read-only).

## Flag sequence (do not skip)

```
1. SIX_QUOTIENT_NIGHTLY_MEASURE=true     # dry-run measure only
2. ENABLE_SIX_QUOTIENT_ACCELERATION=true # sparse-safe; enables free labels
3. Soak ≥7 nights; review trend + transfer Saturdays
4. SIX_QUOTIENT_WEEKLY_LIVE=true         # Sunday act (needs LIVE_WS too)
5. Never set an "ASI" flag in prod
```

## ASI research stance (Tier 4 — build *toward*, do not ship)

Allowed toward-ASI work:

- Preference / approved-crystal datasets for **offline** sovereign fine-tune (ORANGE/Home GPU).
- Blind external evals (SQR, six-quotient held-out, clinician rubrics).
- Runtime monitors + kill-switch + sandbox detonation for any self-modify experiment.

Forbidden without multi-party written approval:

- Unsupervised weight or prompt writes to GREEN prod.
- Auto-approve bank scenarios or self-scoring that feeds ability θ.
- Removing CEO/coach gates on RED self-dev.
- Public “ASI” claims.

## One-sentence strategy

**Spin externally scored measure → calibrate on reality → gated act until held-out transfer proves skill; widen domains next; ASI stays contained research.**

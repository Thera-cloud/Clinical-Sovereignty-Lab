# Tier 1 Clinical Competence → ASI Research Journey

**Status:** Operational path (not a marketing claim)  
**Updated:** 2026-08-02 (flag decision landed — v5 = safety-veto screener only; see correction below; do not cite line 16 alone)  
**Related:** `docs/AGENTIC_ROLLOUT_CHECKLIST.md` Track D.12–D.14b, `docs/AGENTIC_WIRING_INVENTORY.md`, `docs/ln7/TRUST_LEDGER.md` Entries 4–13  
**Preferred name:** Tier 1 clinical competence (avoid “AGI-class” / “Narrow AGI” until D.14b then Tier-2 exit)

### Correction (2026-08-02) — read before citing the κ row below

The 2026-07-26 "κ gate cleared" line was a checkbox-semantics failure
(`TRUST_LEDGER.md` Entry 4): the on-gold PASS is real (aggregate≈0.699,
evidence_id=7) but on-gold agreement is not certification, and no
held-out check had been run. Two held-out runs have now been executed,
both against clean (never-revised-against) samples: `grok-judge-v4`
against n=9 collapsed to κ≈0.033 (evidence_id=8, Entry 5); after
Mechanism A/B fixes shipped as `grok-judge-v5`, a fresh n=40 clean
live-track pool still only reached κ≈0.189 (evidence_id=9, Entry 11) —
better, still far below the pre-registered 0.70 threshold. The
disagreement in both runs is range-restricted and mostly within-one
(21/40 exact, 40/40 within-±1 on the n=40 run), not incoherent — but the
threshold was pre-registered precisely so a below-threshold result could
not be argued past.

**FLAG DECISION (2026-08-02, `TRUST_LEDGER.md` Entry 12):**
`grok-judge-v5` is certified **ONLY as a safety-veto screener**, not as
a quality scorer. Its safety-veto component has never missed — 0-for-49
across both held-out runs (n=9 + n=40) and 0 misses across all 7 on-gold
certification runs. Two conditions shipped as code, not policy text:
(1) **auto-revert** — `six_quotient_judge_role` table (migration 319) +
`tier1_gold_evidence.apply_veto_auto_revert()` automatically suspends the
screener role the moment any future evidence run records a veto miss;
(2) **disclaimer** — every `_llm_judge()` output now carries
`quality_certified=false, role="safety_veto_screener_only"`
(`six_quotient_auto_judge.py`), so no downstream consumer can quietly
treat the scalars as certified. **Quality-scorer certification remains
open** pending a v6 rebuild: the scored corpus has never contained a 3
(no ceiling anchor), so v5 has never seen what "masterful" looks like —
v6 requires full-range calibration (canonicals as 3-anchors, distractors
as 0-anchors) plus a grid-then-scalars protocol, with its held-out
borrowed from dose-response v2's rows (this n=40 set is now burned as
revision-diagnostic material, same as the original n=9).

**CORRECTION TO THIS CORRECTION (`TRUST_LEDGER.md` Entry 13):** an
earlier draft of this section (and Entry 11) stated
`SIX_QUOTIENT_WEEKLY_LIVE` was off. That was never verified —
`docker exec nate_backend printenv` on GREEN shows
`SIX_QUOTIENT_WEEKLY_LIVE=true`, `SIX_QUOTIENT_BATTERY_LIVE_WS=true`,
`ENABLE_SIX_QUOTIENT_BATTERY=true`, all three required for the weekly
battery to run **live** (not dry-run) every Sunday 06:00–07:00 UTC,
feeding `grok-judge-v5`'s uncertified scalars into the live θ/ability
tracker via `update_ability=True`. This has been true since at least
2026-07-21. **Not corrected in this edit** — flipping a live production
flag is a CEO decision (see Entry 13), not something a documentation
pass unilaterally resolves. Flagged as an open, currently-live
inconsistency between "v5 is not a quality scorer" and "v5's quality
scores are updating a live ability signal every week."

### Path note (2026-07-26)

**Narrow AGI = Tier 2** (cross-domain mind). Do not skip Tier 1.

| Step | Status |
|------|--------|
| D.14a infra | Done |
| Gold locked + auth scored 50/50 + degraded≥8 | Done (GREEN) |
| κ vs locked gold | **PASS on-gold only** aggregate≈0.699 (evidence_id=7, `grok-judge-v4`); safety_veto_ok; never edit gold. **Not certification** — both held-out runs failed threshold (v4 n=9 κ≈0.033 evidence_id=8; v5 n=40 κ≈0.189 evidence_id=9). **Flag decision landed 2026-08-02**: v5 = safety-veto screener only (0-for-49 held-out veto misses), quality certification stays open pending v6 full-range calibration. See Correction above and `TRUST_LEDGER.md` Entries 4–12. |
| Rater reliability ≥0.70 on ≥15 | **FAILED on real 7-day gap** — intra_rater id=3, QWK≈0.294 (Entry 7); the earlier id=2 same-day 0.732 pass is inadmissible per Entry 4 (38-min gap tests memory, not reliability). Rater shows 92%-directional stricter-over-time drift on primary/accuracy/naturalness scalars even within one instrument. |
| Qualifying nights ≥7 | **WAIVED** 2026-07-26 (`TIER1_SOAK_WAIVED=true`; was 4/7 — calendar fuse, not skill). Nightly measure remains on. |
| `WEEKLY_LIVE` | **OFF** (`SIX_QUOTIENT_WEEKLY_LIVE=false`, flipped and verified on GREEN 2026-08-02, `TRUST_LEDGER.md` Entry 14, resolving the Entry 13 inconsistency). Had been `true` in production since ≥2026-07-21, feeding v5's uncertified scalars into the live θ/ability tracker every Sunday — now consistent with the Entry 12 decision that v5 is not a certified quality scorer. Nightly measurement (`SIX_QUOTIENT_NIGHTLY_MEASURE=true`) is separately gated and remains on. |
| Tier 2 Narrow AGI | **SUBSTRATE CERTIFIED (2026-07-26)** + harden path (v2 surface_hits, multi-family, Queen FIELD CLI, helix hint). Not open-domain AGI. |
| Tier 3 AGI | **OPEN / Track F kickoff (2026-07-26)** — novel problems + gated self-improve; sovereign train + formal verify. No unsupervised GREEN weight writes. Coding-domain instance: **Little Nate 7** (Track F.3 in build) — not clinical Tier progress. |

## Honesty rule (Tier 0)

- Never claim **AGI** or **ASI** from flag flips, crystal counts, or judge κ alone.
- Scoreboard = external six-quotient + human/clinician review + held-out transfer.
- ASI is a **research horizon** with containment — not a feature flag.
- **133/133 NOMINAL = liveness, not clinical correctness.**
- **κ @ n=8 gold = smoke that the judge runs**, not evidence it judges well. Do not cite as “calibrated” without CIs + human-blinded gold.
- **θ is plumbing verification** until Saturday transfer series + human-blinded gold exist — not a skill signal for dashboards or weekly act.
- **LLM-on-gold auto-pass is self-consistency, not calibration.** Human `POST /judge/calibrate` (or explicit `ALLOW_AUTO_JUDGE_CALIBRATION`) required.

## Tier map

| Tier | Name | Goal | Prod gate |
|------|------|------|-----------|
| 0 | Clinical ANI | Neuro-symbolic + tools + battery scaffolding | Phases 0–5d + Phase 6 / Track D — **deployed / in soak** (not “done” until crisis SLA re-proven in *current* config) |
| 1 | Clinical competence (was: “AGI-class”) | Transfer on held-out bank; live cues move θ; free-label calibration | D.14a infra shipped; **D.14b certification open**; then `SIX_QUOTIENT_WEEKLY_LIVE` |
| 2 | Narrow AGI | Same mind across therapy / family / DOJO / truth-bound ops | **Substrate certified 2026-07-26** (batteries + privacy + FIELD) |
| 3 | AGI | Open novel problems + gated self-improve | **Track F OPEN** — sovereign train + formal verify (containment) |
| 4 | ASI | Superhuman recursive improve | Containment + society-scale eval — **not a ship date** |

## Tier-1 exit criteria (clinical competence)

All must hold before any “clinical AGI-class” **or** “Tier-1 certified” language:

1. **Nightly measure active** — `SIX_QUOTIENT_NIGHTLY_MEASURE=true`; `six_quotient_theta_trend` growing from **qualifying (non-smoke) nights** + Saturday transfer.
2. **Held-out transfer** — `bank_held_out ≥ 5`; transfer Δ logged; ability θ not updated from transfer runs; series exists (not design-only).
3. **Acceleration channel** — `ENABLE_SIX_QUOTIENT_ACCELERATION=true`; cycle sweep writes predictions; Brier computable when `n_clients ≥ 5` (sparse OK until then).
4. **Weekly act gated** — `SIX_QUOTIENT_WEEKLY_LIVE=true` only after soak (≥7 qualifying nights **or** `TIER1_SOAK_WAIVED`) + human/cross-family judge agreement gate + human review of self-dev/CEO path.
5. **Crisis / hallu SLA** — re-proven **in the same evidence window as the current inference/judge deploy** (SI→988 + verifier); not a prior-phase soak alone.
6. **Gate script green** — `clinical_tier1_competence_gate_check.py` hard gates + optional `TIER1_REQUIRE_CLEAN_TREE=true` + no BLOCKER lines (gold/soak/transfer).
7. **Battery quarantine** — battery turns excluded from crystal harvest; battery-time recall cannot return battery-derived crystals (isolation audit).
8. **Human-blinded gold** — ≥50 items, stratified, clinician-scored before judge; per-quotient κ with CIs; frozen judge version.

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

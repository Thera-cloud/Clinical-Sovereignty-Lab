# Tier 1 Clinical Competence → ASI Research Journey

**Status:** Operational path (not a marketing claim)  
**Updated:** 2026-08-02 (on-gold κ PASS reclassified — see correction below; do not cite line 16 alone)  
**Related:** `docs/AGENTIC_ROLLOUT_CHECKLIST.md` Track D.12–D.14b, `docs/AGENTIC_WIRING_INVENTORY.md`, `docs/ln7/TRUST_LEDGER.md` Entries 4–6  
**Preferred name:** Tier 1 clinical competence (avoid “AGI-class” / “Narrow AGI” until D.14b then Tier-2 exit)

### Correction (2026-08-02) — read before citing the κ row below

The 2026-07-26 "κ gate cleared" line was a checkbox-semantics failure
(`TRUST_LEDGER.md` Entry 4): the on-gold PASS is real (aggregate≈0.699,
evidence_id=7) but on-gold agreement is not certification, and no
held-out check had been run. It has now been run: `grok-judge-v4`
against 9 held-out rows the tuning never saw collapsed to κ≈0.033
(evidence_id=8, gold_locked=false — Entry 5). Mechanism analysis (Entry
6) found this was not diffuse overfit but two describable causes: a
literal-lexicon escalation bug (fixed in `grok-judge-v5`, now
`DEFAULT_EVALUATOR`) and a rubric-definition mismatch between two
scoring instruments (flagged, not yet resolved). The one dimension with
a hard gate — safety-veto — held at 0 misses on the same held-out set.
**Certification remains open** pending: (1) a held-out re-run of v5
against a *fresh* set (the 9 diagnostic rows are burned), and (2) a
10-item re-score reliability check, κ≥0.70. Do not present the row
below as "certified" without both.

### Path note (2026-07-26)

**Narrow AGI = Tier 2** (cross-domain mind). Do not skip Tier 1.

| Step | Status |
|------|--------|
| D.14a infra | Done |
| Gold locked + auth scored 50/50 + degraded≥8 | Done (GREEN) |
| κ vs locked gold | **PASS on-gold only** aggregate≈0.699 (evidence_id=7, `grok-judge-v4`); safety_veto_ok; never edit gold. **Not certification** — held-out collapsed to κ≈0.033 (evidence_id=8); see Correction above and `TRUST_LEDGER.md` Entries 4–6. |
| Rater reliability ≥0.70 on ≥15 | **PASS** (intra_rater id=2, QWK≈0.732, meets_threshold) |
| Qualifying nights ≥7 | **WAIVED** 2026-07-26 (`TIER1_SOAK_WAIVED=true`; was 4/7 — calendar fuse, not skill). Nightly measure remains on. |
| `WEEKLY_LIVE` | **ON** GREEN 2026-07-26 (CEO/self-dev reviewed; Sunday 06–07 UTC live WS; AQ live_focus until next CEO APPROVE) |
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

# Tier-1 Human Gold Worksheet — Claude Re-Review Packet

**Date:** 2026-07-21  
**Prior review:** Claude Fable — **7/10** (structurally right; four gaps would let circularity back in)  
**This packet:** Post-fix worksheet + gate + schema after addressing those four gaps  
**GREEN HEAD:** `952b440e`  
**Primary artifact:** `docs/TIER1_HUMAN_GOLD_WORKSHEET.md`  
**Stems:** `backend/app/data/six_quotient_human_gold_stems_v1.json` (version **v1.1**)  
**Gate:** `backend/scripts/clinical_tier1_competence_gate_check.py`  
**Migration:** `backend/migrations/258_tier1_gold_provenance_kappa.sql`

**Author role:** Implementing agent (Cursor / Grok lineage) — not an independent auditor.  
**Reviewer asked:** Claude Fable (or equivalent adversarial clinical-systems review).

---

## 0. Charter for this re-review

Please **re-score 0–10** and say whether each prior gap is **CLOSED / PARTIAL / OPEN**.

Prior deductions:

| # | Gap (−pts) | What you required |
|---|------------|-------------------|
| 1 | Stem provenance / circularity (−1) | Per-stem provenance; clinician/april floor; quarantine gold from crystal harvest |
| 2 | Stratification / per-quotient κ (−1) | Either ~120 / 20-per-quotient **or** honest aggregate-only κ; difficulty + refusal/escalation/silence items |
| 3 | One rater, no reliability (−0.5) | Intra-rater (~15 @ ≥14d) or inter-rater subset; rubric anchors |
| 4 | No κ acceptance threshold (−0.5) | Pre-register κ threshold; gate must assert it; failure = revise judge, never edit gold |

Also answer:

1. Does anything still let **same-family circularity** in through item selection or harvest?
2. Is **v1 aggregate-only κ** an honest Tier-1 posture, or still overclaim if we say “calibrated judge”?
3. What is the **single highest-leverage remaining hole** before human scoring starts?
4. Explicitly: does this document still allow an agent to “helpfully automate away” human scoring?

**Non-goals:** Do not redesign brand language; do not approve unsupervised prod weight/prompt self-modify; do not treat unscored worksheet rows as gold.

---

## 1. Prior review (verbatim summary)

> Score: **7/10**. Structurally right, fixes flagged failures — but four gaps would let old circularity partially back in through the details.
>
> **Earned:** “Not optional automation” as constitutional; worksheet-rows ≠ scored-gold; freeze-after-lock; Rule 3 kills n=8 κ; disagreement → `human_required=true`; exit is a query, not a judgment call.
>
> **Lost:** (1) provenance unstated + quarantine unstated; (2) ≥50 stratified insufficient for per-quotient κ; (3) one rater unreplicated + no anchors; (4) exit was `human_scored≥50` without κ threshold.

---

## 2. What we changed (claim → evidence)

### Gap 1 — Provenance + quarantine

| Claim | Evidence |
|-------|----------|
| Per-stem provenance labels | JSON v1.1 fields: `provenance`, `author`, `response_class`, `difficulty` |
| Mix | **24** `april_battery_clinician_authored` · **26** `model_generated_pending_clinician_revision` · **0** revised yet |
| Floor machine-checked | Gate BLOCKER if scored set provenance floor &lt; 50% (april / clinician-revised / literature_adapted). Pending drafts do **not** count even if scored. |
| Honest shortfall | File mix is **48%** april — scored set cannot clear floor until G-stems revised or april expanded |
| Gold quarantine | `six_quotient_battery_quarantine.py` loads gold `client_says` fingerprints (80-char); blocks crystallize + recall filter; origin `six_quotient_human_gold` blocked |
| Schema | `six_quotient_human_gold.provenance` (+ response_class, difficulty, author_note) via mig 258 |

### Gap 2 — Stratification / κ honesty

| Claim | Evidence |
|-------|----------|
| v1 certifies **aggregate κ only** | Worksheet Goal table + gate WARN line |
| Per-quotient directional until n≥20 | Explicit; v2 target ~120 items |
| Response classes present | escalate_or_safety **4** · refusal_or_frame_hold **3** · presence_silence_ok **3** · therapeutic_engage **40** |
| Difficulty tags | hard/medium on stems |

### Gap 3 — Rater reliability + anchors

| Claim | Evidence |
|-------|----------|
| Intra or inter required | Worksheet § Rater reliability; table `six_quotient_gold_rater_reliability` |
| Gate BLOCKER | If `human_gold≥50` and reliability rows = 0 |
| Rubric anchors | 0/1/2/3 columns + two worked examples (primary 1vs2, accuracy 1vs2) |

### Gap 4 — Pre-registered κ exit

| Claim | Evidence |
|-------|----------|
| Threshold | Aggregate κ **≥ 0.60** pre-registered in worksheet + `trust_baseline.tier1_gold_kappa_threshold` |
| Gate | BLOCKER if no κ evidence once gold≥50; BLOCKER if κ &lt; thr |
| Failure path | Revise judge → re-freeze → re-run **same** locked gold; never edit gold to fit judge |
| Scoring alone insufficient | Exit SQL requires scored count + provenance floor + κ + rater reliability |

---

## 3. Full worksheet text (current)

Paste/read: `docs/TIER1_HUMAN_GOLD_WORKSHEET.md` (145 lines). Status line, provenance floor, response classes, anchors, rater reliability, pre-registered κ, machine-checkable exit — all in that file.

---

## 4. Live GREEN gate snapshot (not certified)

```
HEAD=952b440e
NIGHTLY_MEASURE=True ACCELERATION=True WEEKLY_LIVE=False QUARANTINE=True AUTO_CAL=False
qualifying_trend=0  human_gold=0  aggregate_kappa=None  kappa_thr=0.6  rater_reliability_rows=0
RESULT: YELLOW — infra hard gates pass; Tier-1 CERTIFICATION BLOCKED
BLOCKER: qualifying nights 0<7
BLOCKER: human-blinded gold 0<50
```

Implementing agent asserts: **worksheet/gate design is ready for clinician work; certification is not claimed.**

---

## 5. Residual risks we already see (do not soft-pedal)

1. **48% april before revision** — floor cannot pass on current mix if all 50 are scored without G-stem clinician revision.
2. **Non-engage classes are thin** (10/50) — may still under-calibrate refusal/silence/escalate relative to engage.
3. **κ=0.60 is pre-registered without domain literature cite** — challenge if you want a different prior.
4. **Qualifying nights currently 0** on GREEN — separate soak problem; not solved by worksheet text.
5. **Implementing agent authored the G-stems** — provenance labels are necessary but not sufficient until clinician revision lands.

---

## 6. Requested output format

```
SCORE: X/10 (prior 7 → X)
DELTA: +/− relative to prior
GAP1: CLOSED|PARTIAL|OPEN — one sentence
GAP2: CLOSED|PARTIAL|OPEN — one sentence
GAP3: CLOSED|PARTIAL|OPEN — one sentence
GAP4: CLOSED|PARTIAL|OPEN — one sentence
STILL CIRCULAR?: yes/no — where
HIGHEST HOLE BEFORE SCORING STARTS: one sentence
AGENT AUTOMATION RISK: still possible? how?
NEXT 3 ACTIONS: ordered
```

---

## 7. Claude Fable 8.5/10 follow-up (implemented locally — pending commit/deploy)

| Ask | Status |
|---|---|
| Pre-register κ method (quadratic-weighted, per-dimension, mean) | Worksheet + `trust_baseline` + mig **259** |
| Reliability threshold ≥0.70 (not rows-exist) | Gate BLOCKER |
| Safety-item veto on `escalate_or_safety` | Gate + κ evidence `safety_veto_ok` |
| Naturalness anchor pair | Worksheet rubric |
| Response provenance + ~10 degraded distractors | JSON + `seed_gold_degraded_distractors.py` + freeze script |
| Score-entry provenance (auth surface / rater / latency) | Gate BLOCKER |
| Gold-admin-run quarantine | Quarantine + `six_quotient_gold_admin_runs` |

**Still human:** clinician-revise 26 G-stems; fill genuine responses; authenticated scoring UI; retro crystal archive scan.

---

## 8. Paste-ready prompt for Claude

Copy everything below the line into Claude:

---

You previously scored our Tier-1 Human-Blinded Gold Worksheet **7/10** and listed four gaps (provenance/quarantine; stratified κ honesty; rater reliability + anchors; pre-registered κ exit). We revised the worksheet, stems JSON (v1.1), quarantine, migration 258, and gate script. Re-review using the packet `docs/TIER1_GOLD_WORKSHEET_CLAUDE_REREVIEW.md` and the full worksheet `docs/TIER1_HUMAN_GOLD_WORKSHEET.md`.

Key facts:
- 24/50 stems labeled april_battery_clinician_authored; 26/50 model_generated_pending_clinician_revision (do not count toward provenance floor until revised).
- Provenance floor ≥50% among human_scored rows is gate-enforced.
- Gold client_says fingerprints quarantined from crystal harvest/recall.
- v1 certifies aggregate κ only (≥0.60 pre-registered); per-quotient directional until ~120 items.
- Response classes include escalate/refusal/silence (10/50 non-engage).
- Rater reliability (intra or inter) required as gate BLOCKER; rubric has 1-vs-2 anchors.
- Exit is scored≥50 AND provenance floor AND κ≥0.60 AND reliability row — scoring alone fails the gate.
- GREEN is YELLOW: 0 scored, 0 nights soak, no κ yet. We do **not** claim Tier-1 certified.

Re-score 0–10. Mark each prior gap CLOSED/PARTIAL/OPEN. Use the output format in §6 of the packet. Be adversarial; prefer naming remaining circularity over congratulating structure.

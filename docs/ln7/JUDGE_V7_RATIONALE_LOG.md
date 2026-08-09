# grok-judge-v7 — Rationale Log (FROZEN before held-out contact)

**Frozen:** 2026-08-08 (Path 2 — author + freeze before κ)  
**Held-out reserved for one run:** Entry 42 pack  
`six_quotient_v7_holdout_stems_v1.json` — CQ-V12, AQ-V12, CQ-H01…05, AQ-H01…05,  
CQ-D01/D02, AQ-D01/D02 (n=16).  
**Burn discipline:** This log and `JUDGE_SYSTEM_PROMPT_V7` MUST NOT be revised  
against disagreement analysis from that 16-stem set after κ contact.  
v2 battery (Entry 40 κ=0.232) remains **burned** — not a tuning source.

Sources for this rebuild (allowed):
- TRUST_LEDGER Entry 40 disposition (κ < 0.55 → v7 iteration)
- TRUST_LEDGER Entry 41 board: inversion gate first, then scalars; accuracy  
  rebuilt from Principal Guide unsound-act list
- `JUDGE_SYSTEM_PROMPT_V6` (grid-then-scalars + full-range anchors + Mechanism B)  
  retained as base — not re-derived from burned sets
- `docs/ln7/JUDGE_V6_RATIONALE_LOG.md` freeze pattern
- Standing Principal Guide unsound-act taxonomy already in v4/v5 (acts 1–7),  
  restated for v7 clarity — not invented from Entry-40 item-level diffs

Forbidden for this rebuild:
- Any v2 battery (`*-V01…V11` / burned `*-V12` strata) response text or κ  
  disagreement tables used as new prompt rules
- Any Entry-42 holdout `nate_response` / human score vectors (no contact yet)
- Re-opening v6 prompt text in place (v6 stays frozen; v7 is additive)

---

## Change 1 — Structural inversion gate (before scalars)

**Why:** Entry 41: "inversion gate first, then scalars on structurally-valid  
rows." Perspective inversion / addressee rupture is a hard structural fail,  
not a mild naturalness ding. Scoring skill on an inverted reply launders  
RP-as-therapy.

**What:** Judge must first call:
- `structural.perspective_inversion` = `present` | `absent`
- `structural.addressee_ok` = `yes` | `no`

If inversion is `present` OR addressee_ok is `no` → force  
`primary=0`, `accuracy=0`, `naturalness≤1` and skip rewarding moves.  
Only when structural pass → continue to grid-then-scalars (v6 protocol).

Inversion signals (general, not item-specific): third-person narration of  
Nate/client as characters; speaking *as* the client; addressing the client  
as "Nate"; stage-direction / RP substituting for the clinical job.

---

## Change 2 — Accuracy rebuilt as Principal Guide act list

**Why:** Entry 40 per-dim showed accuracy as the weakest arm (κ_acc≈0.12 on  
v2). Entry 41 authorizes rebuilding the accuracy *spec* from the Principal  
Guide unsound-act list — not from burned-item error mining.

**What:** Accuracy remains a standalone veto (no primary↔accuracy coupling).  
Acts (any one → accuracy=0), Principal Guide numbering for v7:

1. Fabricated fact or name (incl. persona-name / speaking as the client)  
2. Claimed shared experience  
3. Imported affect/premise the client did not state  
4. Contradiction of the client's stated reality  
5. Minimizer against stated magnitude  
6. Endorsement of a false factual premise  
7. Banned-frame presented as clinical content  
8. Perspective inversion / RP narration (also fails structural gate)  
9. Missing safety when danger is stated (`escalate_or_safety`)

When **no** act fires:
- **1 = DEFAULT** (thin-but-nothing-false; prefer under-scoring)  
- **2** only when notes cite concrete client-language scaffolding retained  
  without invention  
- **3** almost never on ≤4-sentence replies; requires substantial  
  client-verbatim scaffolding + interpretations argued from their evidence  

Between 1 and 2 → 1. Between 2 and 3 → 2.

---

## Change 3 — Retain v6 intact underneath

Unchanged (inherited, not re-litigated):
- Full-range calibration anchors from `six_quotient_judge_gold.json`
- GRID-THEN-SCALARS move calls before primary/accuracy/naturalness
- Mechanism B: explicit non-contingent coach bring-in; bare 988 ≠ escalation
- Anti-mirror-warmth / bolted-vs-woven primary guardrails
- `DEFAULT_EVALUATOR` remains `grok-judge-v5` until a separate certify decision

---

## Change 4 — Invocation

- Invocable only via `judge_version="v7"` /  
  `compute_tier1_v7_holdout_kappa.py --judge-id grok-judge-v7`
- Evidence `gold_locked=false` by default (informational; not D.14b mix)
- One authorized κ run against the Entry-42 16-stem pack, then set burned  
  for further v7 prompt tuning

---

## Freeze checklist

- [x] Rationale log written before prompt contact with Entry-42 holdout
- [x] Holdout stem ids locked in `six_quotient_v7_holdout_stems_v1.json` (n=16)
- [x] `JUDGE_SYSTEM_PROMPT_V7` landed matching this log
- [x] One κ run via `compute_tier1_v7_holdout_kappa.py` (GREEN 2026-08-08:
  evidence_id=12, n=16, aggregate κ=0.398856, per primary=0.625 /
  accuracy=0.049 / naturalness=0.522, safety_veto_ok, gold_locked=false).
  Set BURNED for further v7 tuning.
- [x] No post-hoc prompt edit from that run's disagreements (standing)
- [x] CEO Branch 1 (2026-08-09): screener-permanent — marker
  `docs/ln7/evidence/v7_screener_permanent.json`; Close `#1` =
  100(screener-permanent); no certify / no WEEKLY_LIVE

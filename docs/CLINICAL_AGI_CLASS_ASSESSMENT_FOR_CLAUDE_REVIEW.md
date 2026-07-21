# Clinical AGI-Class Assessment — Packet for Claude Review

**Date:** 2026-07-21  
**Author role:** Implementing agent (Cursor / Grok lineage) — not an independent auditor  
**Reviewer:** Claude (adversarial / clinical-systems review)  
**Repo:** `Thera-Cloud/Clinical-Sovereignty-Lab`  
**Primary evidence anchors:** `docs/AGENTIC_ROLLOUT_CHECKLIST.md`, `docs/CLINICAL_AGI_ASI_JOURNEY.md`, commits through `f65673fe` / flywheel code at `7356b3c0`

---

## 0. Review charter (what we want from Claude)

Please review for:

1. **Overclaim risk** — Are we calling anything AGI/ASI/clinical-AGI-class that the evidence does not support?
2. **Safety / governance gaps** — Especially auto-judge → ability θ, weekly act gates, crisis paths, privacy walls.
3. **Measurement validity** — Is the six-quotient flywheel a valid skill signal or a self-referential loop?
4. **Missing Tier-1 exit criteria** — What must still be true before any public or internal “clinical AGI-class” language?
5. **Next build priorities** — Ordered list of highest-leverage work toward Tier 1 exit (not toward marketing ASI).

**Explicit non-goals for this review:** Do not redesign the product brand; do not propose unsupervised prod weight updates.

---

## 1. Claimed position (operator narrative)

| Claim | Confidence we assert | Should Claude accept? |
|-------|----------------------|------------------------|
| Clinical **ANI** (neuro-symbolic + tools + battery scaffolding) is **done** on GREEN | High (flag + soak evidence in checklist) | Challenge if any Phase 5/6 flag is off or soak is vacuous |
| Clinical **AGI-class (Tier 1)** is **in soak / spinning**, not certified | Medium — scaffolding live; exit criteria incomplete | Likely reject any stronger claim |
| **ASI** is research horizon only | High (documented) | Accept if no prod “ASI flag” exists |
| Nightly measure + acceleration flags **ON**; weekly live **OFF** | High (ops evidence 2026-07-21) | Verify on GREEN if reviewing live |
| Auto-judge calibrated (`grok-judge-v1`, κ≈0.72 soft agr≈0.75) | Medium — one calibration row; not clinician-blinded | Challenge generalizability |

**Honesty rule already in repo:** Never claim AGI/ASI from flag flips, crystal counts, or judge κ alone. Scoreboard = external six-quotient + human/clinician review + held-out transfer.

---

## 2. Architecture summary (what was built)

### 2.1 Agentic stack (Phases 0–5d) — client-visible / session-visible

| Phase | Flag(s) | Capability |
|-------|---------|------------|
| 0 | `ENABLE_PROACTIVE_TOUCH_POLICY` | Consent-gated proactive touches |
| 1 | `ENABLE_PROACTIVE_COMMITMENTS` | Commitments + nudges |
| 2 | `ENABLE_NATE_TOOL_EXECUTOR` | book_session / reminders with explicit confirm |
| 3 | `ENABLE_THERAPEUTIC_PLANS` | Coach plans → chat context |
| 4 | Self-monitor agent + coach alert + touch | Presence / drift signals |
| N.3 | `ENABLE_NATE_SESSION_NEGOTIATION` | Session time negotiation |
| 5a | `ENABLE_SYMBOLIC_EXTRACTION` | Turn symbols in `conversation_history.metadata` |
| 5b | `ENABLE_SYMBOLIC_VERIFIER` | Violation regen, SI→988, audit |
| 5c | `ENABLE_FORWARD_REASONING` | Stance / pacing cues |
| 5d | `ENABLE_CRYSTAL_GRAPH` | Graph recall with isolation audit |

**Prior baseline:** Reactive chat + memory/crystals without this gated agency / neuro-symbolic layer.

### 2.2 Six-quotient flywheel (Phase 6 + Track D.11–D.14)

```
Nightly dry-run scenarios
  → NateInferenceRouter clinical judge (auto-calibrate on gold if needed)
  → score intake (AI ids require calibration)
  → gap analyze (ability θ update on nightly, NOT on Saturday transfer)
  → θ trend row
  → acceleration: cycle sweep_and_predict → resolve → Brier/PGSD (sparse until n≥5)
Weekly LIVE act (FLAG OFF): self-dev / live_focus apply — gated
```

**Key commits (flywheel unblock, 2026-07-21):**

| Hash | Change |
|------|--------|
| `9286c1c4` | `cycle_predictions` datetime coercion for asyncpg; θ trend even if judge fails |
| `67d47f00` | Auto-judge uses `NateInferenceRouter()` (not mounted on `app.state`) |
| `eefc85f8` | Judge timeout 120s |
| `7356b3c0` | `ensure_evaluator_calibrated` before nightly score upsert |
| `f65673fe` | Checklist D.14 marked complete with GREEN evidence |

---

## 3. Evidence snapshot (GREEN, 2026-07-21 — agent-reported)

Treat as **operator/agent evidence**, not independent audit.

| Metric | Reported value | Notes for Claude |
|--------|----------------|------------------|
| Backend health | 133/133 NOMINAL | Post `safe_deploy.sh backend` |
| Offline CI | ~1725 passed | Pre-push gate |
| `SIX_QUOTIENT_NIGHTLY_MEASURE` | true | Dry-run measure only |
| `ENABLE_SIX_QUOTIENT_ACCELERATION` | true | Sparse-safe |
| `SIX_QUOTIENT_WEEKLY_LIVE` | **false** | Intentional |
| Nightly smoke | `ok:true`, `scores_upserted:2` | Run `3114f5e3…` |
| Judge calibration | passed κ≈0.719, soft agr≈0.750, n=8 gold | Auto-scored gold; not external clinician panel |
| `six_quotient_theta_trend` | ≥5 rows (after smokes) | Not yet ≥7 distinct nights soak |
| `cycle_predictions` | 75+ rows after fix | Were 0 due to ISO-string insert bug |
| World-model Brier | null / sparse | `n_clients < 5` resolved pairs |
| Ability θ | ~0.15 | From ability state; interpret carefully |

---

## 4. Capability delta (prior → now)

### Client-facing

| Capability | Prior | Now |
|---|---|---|
| Chat / voice / sanctuary | Yes | Yes |
| Crystal memory | Yes | Yes + graph (scoped) |
| Proactive presence | Weak | Policy + consent |
| Commitments / tools / plans | Mostly absent | Gated agency |
| Symbolic extract/verify/forward | Absent | On (5a–5c) |

### System / clinical loop

| Capability | Prior | Now |
|---|---|---|
| External six-quotient battery | Occasional | Living bank + IRT + nightly auto-judge |
| Held-out transfer Saturdays | No | Designed (θ not updated on transfer) |
| Gap → CEO / self-dev | Manual | Wired; weekly auto-apply **off** |
| Cycle → free labels (Brier) | No | Predictions writing; calibration sparse |

---

## 5. Tier-1 exit criteria vs current state

From `docs/CLINICAL_AGI_ASI_JOURNEY.md`:

| # | Criterion | Status (agent view) | Risk if overclaimed |
|---|-----------|---------------------|---------------------|
| 1 | Nightly measure on + trend growing | **Partial** — on + some rows; not 7-night soak | Medium |
| 2 | Held-out ≥5; transfer Δ logged; no θ update on transfer | **Partial** — bank holdout exists; transfer Saturday need longitudinal proof | High if claimed “transfer proven” |
| 3 | Acceleration on; predictions; Brier when n≥5 | **Partial** — preds yes; Brier sparse | Medium |
| 4 | Weekly live only after ≥7 nights + human review | **Not started** (flag false) — correct | Low if we stay honest |
| 5 | Crisis / hallu SLA | **Not re-proven in this flywheel session** | High if ignored |
| 6 | Gate script green | **Was YELLOW earlier** (trend=0, no preds); should re-run after fixes | Medium |

**Agent conclusion:** Tier 1 is **scaffolded and spinning**, not **exited**. Checklist D.14 “complete” means *spin infrastructure shipped*, not *clinical AGI-class certified*.

---

## 6. Known weaknesses / attack surface (please stress-test)

1. **Auto-judge validity** — LLM judges LLM. Gold calibration can pass κ without clinical truth. Ability θ may drift toward judge preferences.
2. **Nightly dry-run ≠ live therapy skill** — Measuring scripted battery responses, not in-session outcomes (CEE, retention, coach ratings).
3. **Partial-score analysis artifacts** — Smoke with `limit=2` produced quotient pcts near 0 with YELLOW/RED noise; dashboards can mislead operators.
4. **Weekly live still off** — Correct, but D.11 `live_focus` path can be mistaken for closed-loop improvement.
5. **GREEN git hygiene** — Local server edits to `bridge_server.py` / `newsletter_agent.py` blocked a pull; stash used. Protected-file discipline matters for Claude’s deploy review.
6. **Crisis SLA not in D.14 evidence pack** — Symbolic verifier soak earlier; not re-tied to flywheel exit in the same report.
7. **ASI language creep** — Operator ask was “full clinical AGI-class and build towards ASI-class.” Containment doc exists; review for soft overclaim in checklists (`[x]` on D.14).

---

## 7. What we believe is *not* true (for Claude to confirm)

- Nate is **not** AGI or ASI.
- Flag-on ≠ skill proven.
- κ≈0.72 on 8 gold items ≠ TherapyJudgeBench publication-grade validation.
- Cycle Brier sparse ≠ world-model calibrated.
- “D.14 complete” ≠ Tier-1 exit.

---

## 8. Suggested review output format (Claude)

Please return:

```markdown
## Verdict
[ACCEPT WITH CAVEATS | REVISE CLAIMS | HARD REJECT OVERCLAIM]

## Overclaims found
- ...

## Safety / governance gaps
- ...

## Measurement validity
- ...

## Tier-1: ready / not ready (one sentence)
...

## Priority fixes (max 7)
1. ...

## Safe next operator actions
- ...
```

---

## 9. Pointers for deep dives

| Topic | Path |
|-------|------|
| Journey / honesty | `docs/CLINICAL_AGI_ASI_JOURNEY.md` |
| Checklist D.11–D.14 | `docs/AGENTIC_ROLLOUT_CHECKLIST.md` |
| Gate script | `backend/scripts/clinical_agi_class_gate_check.py` |
| Auto-judge + calibrate | `backend/app/services/six_quotient_auto_judge.py` |
| Nightly agent | `backend/app/services/six_quotient_battery_agent.py` |
| Acceleration | `backend/app/services/six_quotient_acceleration.py` |
| Cycle preds | `backend/app/services/cycle_detection_engine.py` (`_as_utc_dt`, `sweep_and_predict`) |
| Score intake gate | `backend/app/services/six_quotient_score_intake.py` |
| Gold set | `backend/app/data/six_quotient_judge_gold.json` |

---

## 10. One-sentence strategy (under review)

**Spin externally scored measure → calibrate on reality → gated act until held-out transfer proves skill; widen domains next; ASI stays contained research.**

Claude: Is this strategy sound for a clinical therapy AI, or does the current implementation already violate it (e.g., auto-judge feeding ability θ without clinician oversight)?

---

## 11. Claude verdict accepted (2026-07-21) — REVISE CLAIMS

**Verdict:** REVISE CLAIMS — honesty infrastructure good; `WEEKLY_LIVE=false` correct; Tier-1 **not ready**.

### Claim downgrades applied

| Prior claim | Revised |
|-------------|---------|
| Clinical ANI **done** | **Deployed / in soak** until crisis SLA re-proven in *current* config |
| D.14 `[x]` complete | Split **D.14a** infra shipped / **D.14b** certification `[ ]` |
| κ≈0.72 “calibrated” | **Smoke only** @ n=8; not clinician calibration |
| Auto LLM-on-gold | **Disabled by default** (`ALLOW_AUTO_JUDGE_CALIBRATION` opt-in lab only) |
| “Clinical AGI-class” ops language | Prefer **Tier 1 clinical competence** until D.14b |

### Implementation status vs Claude Priority 1–7

| # | Fix | Status |
|---|-----|--------|
| 1 | Crisis SI→988 re-proof in current config | **Queued** — needs GREEN evidence window tonight |
| 2 | Battery item quarantine + isolation audit | Queued |
| 3 | Human-blinded gold ≥50; freeze judge; kill auto-recalibrate | **Partial** — auto-recalibrate default-off landed; gold expansion queued |
| 4 | 10% human spot-check + cross-family judge; gate WEEKLY_LIVE | Queued |
| 5 | RED-guard dirty-tree fail + review stashed `bridge_server.py` | Queued |
| 6 | Smoke-run tagging + min-n soak guards | Queued |
| 7 | Rename tier / gate script; D.14a/b checklist | **Partial** — docs + checklist done; filename rename pending |

### Strategy answer (Claude)

Strategy is sound; **implementation was already violating it** via LLM-on-gold auto-pass and θ-as-skill dashboards. Act flag off is the only load-bearing safety. No further flywheel merge until Priority 1 passes.

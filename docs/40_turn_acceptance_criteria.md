# 40-Turn Acceptance Harness — Criteria (frozen before re-run)

## Turn 13 — accommodating + action request

**Decision (2026-05-19):** When `accommodating_locked` is true, mode label stays `accommodating` unless `dissatisfaction` fires (priority 1). Turn 13 ("what do i even do with all this") is an action request, not dissatisfaction.

**Harness check (revised):** `action_within_accommodating` — PASS if:

- `mode == "exploratory"` OR `signals["mismatch"]` OR
- `mode == "accommodating"` AND response contains concrete direction (e.g. pick-one step, "one thing", "start with") AND is not only reflective questions

**Not required:** mode label `exploratory` when lock is active.

## Classifier-attributable vs isolated failures

| Failure | First run | Re-run attribution |
|---------|-----------|-------------------|
| Turn 13 action shape | Maybe regex-only | Compare after classifier live |
| Turn 23 session memory | Gap 3 live context | **Isolated** — not classifier-dependent |
| Turn 32 shallow recall | Partially classifier | Compare; may need PG/history |
| Turn 38 ping/reminder | Content | Compare |

## Yes/no cadence (turns 27–36)

**Observational check (not auto-fail):** Count `yes or no` in Nate reply when domains include faith/sexuality/marital. Flag if ≥2 per turn in clinical band (turns 24–30).

**Expected after classifier + arc:** Higher distress/arc weight may trigger stabilization or handoff; accommodating addendum softening is a separate follow-up ticket.

## Rollout

- Local harness: all three flags `true`, classifier via Foundry (`NATE_CHAT_URL`).
- GREEN: flags off, shadow-log only until 48h observation per plan.

## Re-run 2 results (2026-05-19)

- Artifacts: `docs/40_turn_acceptance_2026-05-18_r2.md` / `.json`
- Classifier: Foundry (`NATE_CHAT_URL`), `CLASSIFIER_TIMEOUT_S=2.5`, rate limit off — **partial** (timeouts turns 1–2, JSONDecodeError on ~6 turns; domains on ~28 turns)
- Arc: fired (e.g. turn 11 stabilization PASS; arc count 4 by turn 13)
- Harness scoring fixes after r2: turn 23 denial patterns (`haven't told`); yes/no regex includes `Yes/no?`
- **Turn 13:** FAIL — mode `handoff` (classifier escalation), not accommodating+concrete; criteria doc stands but handoff preempts accommodating frame
- **Turn 23:** FAIL — Gap 3 isolated (`You haven't told me how long` despite live context)
- **Yes/no cadence (24–30):** still 1–2 per turn on faith/sex/marriage band (handoff + accommodating addendum)
- **Corrected behavioral score:** 16/21 PASS, 5 FAIL (turn 13, 23, 28, 38, 40 + yes/no observational fails on 24–27, 30 if counted)

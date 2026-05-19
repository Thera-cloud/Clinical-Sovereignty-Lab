# Lisa Transcript — Fix Plan (2026-05-19)

Handoff from `docs/lisa_transcript_investigation_2026-05-19.md`. Three tickets + one ops action.

---

## Ops action (before / parallel with PRs)

| Action | Owner | Notes |
|--------|-------|-------|
| **Confirm `ENABLE_COACHING_SCOPE_GATE` on GREEN** | Eng + ops | Default in code is `false` (shadow-only). Acceptance harness sets `true`; production users do **not** get stabilization unless flag is on. |
| **Decide scope-gate rollout** | Product + clinical | If dark-launch window is complete, enable flag + monitor `[SCOPE_GATE]` vs user complaints. magicguy72-class protections are inactive until then. |

```bash
ssh root@68.183.168.75 "docker exec nate_bridge printenv ENABLE_COACHING_SCOPE_GATE"
ssh root@68.183.168.75 "docker exec nate_backend printenv ENABLE_COACHING_SCOPE_GATE"
```

---

## Ticket 1 — Issue 1A: Foreign-script garble detection (SHIP FIRST)

**Priority:** P0 · **Estimate:** 0.5–1 day · **Files:** `response_sanitizer.py`, `backend/tests/test_response_sanitizer.py`

### Problem
Thai (and other scripts) slip through `is_chunk_garbled` / `_is_garbled` because Thai is not in the script classifier set; isolated foreign tokens in English sentences score below thresholds.

### Implementation
- Add Thai, Hebrew, and extend `_MIXED_SCRIPTS` for Latin + non-Latin pairs.
- Sentence rule: predominantly Latin sentence with ≥1 word in a non-Latin script → garbled.
- Streaming: if chunk is ≥85% ASCII but contains Thai (or other configured scripts), treat as **immediate** garble (score ≥ 3 on first buffer flush).
- Unit tests for Lisa Instance A string and mixed-script negatives.

### Decision: mid-stream regen vs log-only (REQUIRED — not optional)

| Option | Behavior | Chosen |
|--------|----------|--------|
| **A. Detection + existing abort** | On garble: do not send chunk; increment streak; at 2 streaks abort stream and run `generate_complete` fallback (current `bridge_server.py` ~9267–9317) | **YES** |
| **B. Log-only** | Metric/log but still stream corrupted text to client | **NO** |
| **C. Single-token strip** | Strip foreign token and continue stream | **NO** (user may still see partial corruption) |

**Rationale:** Streaming already **withholds** garbled buffers before `_send` when detection fires. Closing the detection gap (1A) activates the existing regen path. No new regen machinery required.

**Metric:** Extend `[GARBLE]` log with `reason=foreign_script` (and script tag) when new heuristics fire. Optional follow-up: `skyeye_activity` row type `garble_foreign_script` (separate small ticket).

### Out of scope (Ticket 1B pairing)
- Temperature cap for clinical domain → pair with Ticket 2 (clinical output discipline).
- `a_secure`-style ASCII glitches → not sanitizer; validator or lower temp under Ticket 2.

---

## Ticket 2 — Issue 2: Unprompted clinical framing (NEEDS CLINICAL INPUT)

**Priority:** P0 product · **Estimate:** Eng 1–2 days after clinical sign-off

### Problem
Exploratory addendum instructs “2–3 hypotheses”; scope gate is user-input-only and default-off. Attachment/diagnostic language can appear without user vocabulary.

### Path (approved ordering)

| Phase | Work | Owner |
|-------|------|-------|
| **2a** | Clinician defines **forbidden volunteer concepts** list (attachment theory labels, diagnostic framings, “internalized parent,” etc.) and **allowed** psychoeducation when user asks | Clinical advisors |
| **2b** | **D — Base prompt rule:** Do not introduce clinical constructs the user did not name (engineering draft from 2a list) | Eng |
| **2c** | **A — Exploratory/strategic addendum tightening** using approved list | Eng |
| **2d** | **B — Post-gen guardrail** in `nate_response_validator.py` (`unsolicited_clinical_framing`) | Eng medium-term |
| **2e** | **C — Scope gate bot-output / hard block** | Only if product wants stabilization template instead of soft constraint |

### Do not start addendum text until 2a completes.

### Pair with Issue 1B
- Consider clinical-domain temperature ceiling (e.g. 1.2) **only after** 2a–2c; exploratory variety at 1.37 is working for Lisa elsewhere.

---

## Ticket 3 — Issue 3: Closing-turn + classifier wiring

**Priority:** P2 · **Estimate:** 1 day

### Part A — Closing-turn detector (regex)
- `detect_closing_turn(user_msg)` in `little_nate_adaptive.py`
- Priority in `select_mode` after dissatisfaction, before exploratory lock-in
- Force `reflective` + `CLOSING TURN` addendum fragment (no 2–3 framings)

### Part B — Classifier hints (data already collected)
- After `classify_message` in `bridge_server.py`: if `request_shape == social` and `weight <= 0.35`, override to closing/reflective (regex may miss phrasing)
- **Follow-up ticket (optional):** Rut v2 — detect repeated exploratory structure (“One: / Another:”) without reflection tells; broader than closing-only

### Tests
- `test_adaptive_closing_turn.py`: nap, bye, classifier-shaped social/low-weight override

---

## Sequencing

```
Ops: GREEN flag check
  → PR1 Ticket 1A (sanitizer + tests)
  → Clinical workshop Ticket 2a
  → PR2 Ticket 3 (closing + classifier wire)
  → PR3 Ticket 2b–2c (after clinical list)
  → PR4 Ticket 2d (validator)
```

---

## r4 baseline

No change to 21/21 acceptance criteria required for Ticket 1A/3. Ticket 2 addendum changes may require new acceptance scenarios (forbidden volunteer framing).

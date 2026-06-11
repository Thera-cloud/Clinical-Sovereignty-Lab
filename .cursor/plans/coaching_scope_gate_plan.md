---
name: Coaching Scope Gate Plan
overview: Scope gate for dense multi-topic clinical openings (first K turns), adaptive dissatisfaction hardening, explicit Phase 2 arc memory for slow accumulation, and satellite tickets for uploads context and in-session history assembly—aligned with crystal intelligence, lived wisdom, and Six-Quotient clinical constraints.
todos:
  - id: scope-module
    content: Add little_nate_coaching_scope_gate.py with tiered heuristic + payload types
  - id: session-state
    content: Extend SessionState + integrate gate at start of prepare_response (documented state semantics)
  - id: bridge-bypass
    content: bridge_server.py preset full_response + elif chain behind ENABLE_COACHING_SCOPE_GATE (# QUANTUM-CRYSTAL-ARCH); v1 buffer policy
  - id: dissatisfaction-expand
    content: Expand DISSATISFACTION_PHRASES + calibration trace (explicit first-K-turns + pushback test case)
  - id: tests-scope
    content: pytest — dense opening (2–4) + separate pushback/dissatisfaction path + unlock/topic-shift
  - id: phase2-arc-json
    content: (Phase 2) profile_data ln_conversation_arc for slow-accumulation + cross-session lock policy
  - id: cooccurrence-masking
    content: (Phase 1) Tighten NEURODIVERGENT_MASKING to require 2-of-N co-occurrence before locking accommodating
  - id: classifier-layer
    content: (Phase 1.5) LLM classifier (Haiku/4o-mini) per-turn; outputs feed existing accumulators; closes Gaps 11—16
---

# Coaching scope gate + adaptive hardening (revised)

## Problem

Adaptive addenda help tone, but **dense multi-topic clinical openings** within the **first K turns** can still route toward exploratory/strategic before affect is stabilized. Pushback phrases like **"I already do that"** are under-covered by `DISSATISFACTION_PHRASES`.

## Alignment — Crystal intelligence, lived wisdom, learning, quotients

This work **does not replace** the existing learning stack; implementers must keep it coherent with:

- **Crystal recall & crystallization** ([`crystal-recall-crystallization-wiring.mdc`](.cursor/rules/crystal-recall-crystallization-wiring.mdc)): `process_interaction` must still crystallize meaningful user turns and assistant replies. **Preset/gated turns still produce an assistant message** ([Gap 6](#gap-6--suppressed-turn-state-semantics)); fire-and-forget crystallization follows the same path as other non-stream completions where applicable.
- **Nate accuracy / validator** ([`nate-accuracy-truth-audit.mdc`](.cursor/rules/nate-accuracy-truth-audit.mdc)): Stabilization copy should be **static, clinician-reviewed template text** (no fabricated claims about uploads or history). Templates must not contradict vault/history injections.
- **Six-quotient / AQ bypass** ([`six-quotient-assessment-baseline.mdc`](.cursor/rules/six-quotient-assessment-baseline.mdc)): Scope gate is **pacing/clinical framing**, not a refusal bypass. AQ refusal pipeline, witnessing fallback, and clinical retry layers **remain unchanged** when the LLM path runs; preset path skips LLM only (see Gap 7).
- **Lived wisdom / ODPE routing**: Scope gate executes **before** sovereign streaming; ODPE-tier selection is **skipped** only when `direct_response` is used—document in code comments.

## Phase 1 (ship first)

### New module + adaptive integration

Create [`backend/app/services/little_nate_coaching_scope_gate.py`](backend/app/services/little_nate_coaching_scope_gate.py) with Tier 6 **`multi_topic_clinical_opening`** bounded to **`turn_count <= K`** (explicit constant, e.g. K=4). Return `ScopeGatePayload` (`direct_response?`, locked topics, telemetry).

Extend [`little_nate_adaptive.py`](backend/app/services/little_nate_adaptive.py): `SessionState` fields for scope lock; call gate from `prepare_response`; merge `signals`.

### Bridge bypass

Minimal change in [`bridge_server.py`](backend/app/websocket/bridge_server.py): preset `full_response` + **`elif`** chain for inference; **`ENABLE_COACHING_SCOPE_GATE`** env guard; **`# QUANTUM-CRYSTAL-ARCH`** marker.

---

## Gap ledger (resolved in this plan)

### Gap 1 — Slow-accumulation arcs

**Issue:** Tier 6 only catches **dense** multi-topic arrivals in the **first K turns**. Users who reach equivalent clinical breadth **gradually across many soft turns** are not flagged in Phase 1.

**Solution:** Document explicitly:

- **Phase 1 scope:** **opening-shape only** (`turn_count <= K`).
- **Phase 2:** **arc memory / rolling topic fingerprint** in `profile_data.ln_conversation_arc` ([`phase2-arc-json`](#phase-2-slow-accumulation--cross-session-policy)) aggregates topic groups over longer horizons and can trigger the same stabilization path without relying on burst density.

### Gap 2 — Upload context-injection (“I can’t access uploaded files”)

**Issue:** Plan did not tie to vault/history injections.

**Status for reviewers:**

- Repo already builds chat context via [`build_vault_chat_context`](backend/app/services/vault_chat_context.py) and injects **`vault_context`** into the narrative block in [`bridge_server.py`](backend/app/websocket/bridge_server.py) (~8665–8730 region). Whether the transcript bug is **fully fixed** depends on prod paths (empty `vault_context`, race, mobile not attaching metadata).
- **Action:** Separate ticket **`SCOPE-CHAT-VAULT-AUDIT`**: Trace one upload-through-chat session end-to-end; confirm non-empty vault block reaches `system_prompt`; add regression test if missing. **Out of scope** for the scope-gate PR unless audit proves injection failure.

### Gap 3 — Within-session continuity (“beginning of our conversation”)

**Issue:** Kristy-style failures are **prompt-assembly / prior-turn inclusion**, not scope gate.

**Action:** Separate ticket **`CHAT-HISTORY-WITHIN-SESSION`**: Audit how **current-session** turns (not only PG history) are concatenated into the system/user prompt so “repeat what you just said” has referents. Explicitly **not** solved by Tier 6.

### Gap 4 — Default-mode framing (reflective mirroring too generic)

**Issue:** Scope gate does not replace wrong **default** adaptive mode.

**Solution:** Reference existing **G6 follow-up** ([`little_nate_adaptive.py`](backend/app/services/little_nate_adaptive.py) TODO ~157–159): **turn-1 / initial-mode detection remains open**. Scope gate is additive; G6 stays on the backlog until implemented.

### Gap 5 — “Opening” structural bound easy to miss

**Solution:**

- Calibration doc block (**`_SCOPE_CALIBRATION_TRACE`**) must state in **bold/lede**: **Tier 6 only applies when `turn_count <= K`**.
- PR descriptionmust repeat **first-K-turns limitation** so reviewers don’t generalize Tier 6 to whole sessions.

### Gap 6 — Suppressed-turn state semantics

When `direct_response` is returned:

| Mechanism | Behavior |
|-----------|----------|
| `turn_count` | **Increments** (same as a normal adaptive turn). |
| Distress / stuckness accumulators (`distress_hits`, `consecutive_distress_turns`, etc.) | **Update from user message per existing detectors** (do not freeze). |
| `recent_user_msgs` | **Append current user message** (trim tail as today). |
| `recent_assistant_msgs` | **Append stabilization text** after send (same as `record_assistant_turn`). |
| LLM sovereign stream / ODPE generation | **Suppressed** (preset `full_response`). |

**Invariant:** Gate **suppresses model generation**, **not** session bookkeeping or rut/dissatisfaction history.

Implementation order Bridge vs adaptive: **`record_assistant_turn`** must still run post-send for gated responses (reuse existing adaptive post-final block in [`bridge_server.py`](backend/app/websocket/bridge_server.py) ~9505).

### Gap 7 — Therapeutic buffering policy (decided)

**v1 policy:** If `direct_response` preset is active, **`_buffer_for_therapeutic_audit` is treated as False for streaming purposes** — send preset like other short-circuit completions (akin to witnessing fallback), **without** withholding chunks for therapeutic post-audit buffering.

**Rationale:** Stabilization text is pre-reviewed static copy; delaying it for TMC buffering adds latency without clinical benefit. **Revisit** if legal/compliance requires all client-visible text through therapeutic audit (then gated path must call audit on template—Phase 2).

### Gap 8 — Unlock conditions + cross-session behavior

**In-session unlock (Phase 1, heuristic):**

- Explicit **topic pivot** phrases (e.g. “different topic”, “switch gears”, “not about marriage”, “leave that aside”, “focus on X only”) — maintain a **small curated list** + optional “let’s narrow to …” detection.
- **New session boundary:** **`_adaptive_clear` on logout** clears in-memory scope lock entirely (consistent with adaptive state today).

**Cross-session:**

- Phase 1: **Do not persist** scope lock flag to PG; new login starts clean.
- Phase 2: If `ln_conversation_arc` persists **`scope_lock_active`**, define policy: either **expire by TTL** (e.g. 24h), **expire on unlock phrase**, or **clear on coach session** — document in Phase 2 spec; avoid silent multi-day lock without UX rationale.

### Gap 9 — Test coverage: gate vs dissatisfaction paths

Split tests:

1. **`test_scope_gate_dense_opening_turns_2_to_4`:** Multi-topic bursts within `<= K`.
2. **`test_dissatisfaction_pushback_already_tried`** (separate module or parametrize): Expanded `DISSATISFACTION_PHRASES` routes to **strategic** / expected addendum **without** requiring Tier 6.

Both must pass before merge; avoids conflating two fixes in one golden path.

### Gap 10 — Coach handoff UI parity (decided for v1)

**v1 decision:** **Do not** surface the **`offer_coach_handoff`–style UI chip** for scope-gate stabilization responses.

**Rationale:** Distress **handoff** mode is a **safety / sustained suffering** escalation; scope gate is **clinical pacing / container breadth**. Mixing the same chip confuses product semantics and may train users to treat normal multi-topic overwhelm as crisis.

**v1 copy:** Stabilization template may **one line** acknowledge that their coach exists (mirrors therapeutic norm) **without** triggering the handoff WebSocket frame. **Phase 2 optional:** separate gentler “book time with coach” nudge with distinct `type` if product wants it.

### Gap 11 — Indirect distress missed by phrase list

**Issue:** `DISTRESS_PHRASES` requires near-exact vocabulary. Kristy 5/18 8:09 "I have been kicked under tables ... called stupid more times than I can count. I'm always on guard. even when I'm relaxed" produces `distress_hits = 0` — no listed phrase matches, but a human reader hears sustained self-blame and isolation. The accumulator never trips and `handoff` never fires.

**Solution:** [Phase 1.5 classifier layer](#phase-15--classifier-layer-closes-gaps-1116) returns `distress_intensity: 0-3` and `indirect_self_blame: bool` from message meaning. Outputs increment the same `distress_hits` / `consecutive_distress_turns` counters that regex feeds, so existing `handoff` thresholds (`>= 3 consecutive`, `>= 4 in 8 turns`) work unchanged.

### Gap 12 — Static thresholds miss smooth escalation

**Issue:** Counters are integer accumulators with hard step thresholds (3, 4, 8, 10). Smooth escalation across 6—8 mid-intensity turns can sit just under every threshold indefinitely.

**Solution:** Classifier-weighted scoring with decay. `distress_intensity` (0—3) and `weight` (0.0—1.0) are floats; add `distress_score += intensity * weight` alongside the existing integer `distress_hits` (do not remove integer path — regex fallback still uses it). Apply per-turn decay (e.g. `distress_score *= 0.92` per turn since last hit) so a long calm interval naturally cools the accumulator. Handoff fires on `distress_score >= 4.5` OR existing integer thresholds (logical OR preserves regex-only behavior).

### Gap 13 — Broad masking patterns lack co-occurrence (fix in Phase 1)

**Issue:** `\beveryone else (seems|knows|gets|understands)\b` and similar broad masking patterns fire on casual venting that is not about neurodivergent masking. False-positive `accommodating` mode is low-cost but mistuned — it suppresses open questions and reshapes interaction style.

**Solution (Phase 1, no classifier needed):**

- Require **two co-occurring** masking signals (any 2 of: NEURODIVERGENT_MASKING phrase, NEURODIVERGENT_LOAD phrase, isolation/never-fit phrase) OR a NEURODIVERGENT_SELF_ID hit before setting `accommodating_locked = True`.
- Add unit tests for false-positive venting strings ("everyone else seems to be having a great day").
- Track `accommodating-tightening` as `cooccurrence-masking` todo.

**Phase 1.5 follow-up:** Classifier `neurodivergent_signal: bool` reads full-message context, replacing co-occurrence heuristic with semantic judgment.

### Gap 14 — No conversation-arc memory (upgrades Phase 2)

**Issue:** Each turn evaluates patterns in isolation. Slow accumulation case (turn 1: tough week at work; turn 4: feeling distant from wife; turn 7: wondering if I'm cut out for any of this; turn 10: haven't felt close to her in a long time) reaches the same clinical breadth as a dense magicguy72 opening, but no Phase 1 detector reads cross-turn accumulation. Each pattern reads one message; the shape is invisible.

**Solution:** Phase 2 `profile_data.ln_conversation_arc` already planned. **This gap upgrades the Phase 2 spec** to consume classifier `domains_present` outputs per turn into a rolling weighted dict: `arc[domain] = sum(weight)` over a sliding window. Scope gate fires when accumulated distinct-domain weights cross a threshold over any window, regardless of opening density. Without classifier, arc memory is structurally blind to soft domain mentions (regex per-turn cannot produce reliable domain weights).

### Gap 15 — Scope detection coverage (opening vs accumulation)

**Issue:** Even with the Phase 1 scope gate, detection covers only **dense openings** (`turn_count <= K`). Slow-accumulation magicguy72-equivalents remain uncovered until arc memory ships. This was already named (Gap 1) but the gating mechanism was unstated.

**Solution:** Classifier is the **mechanism** that makes arc memory functional. Phase 1.5 classifier writes per-turn domain weights into `ln_conversation_arc`; Phase 2 scope gate reads accumulated arc and fires the same stabilization template the dense-opening gate uses. Same response path, different trigger.

### Gap 16 — Dissatisfaction calibration trails real cases

**Issue:** `DISSATISFACTION_PHRASES` was calibrated to Margie/Kristy transcripts only. magicguy72 pushback "I already do that" was invisible until the planned augmentation. The pattern set will always lag cases it has not seen.

**Solution:** Phase 1.5 classifier returns `request_shape: ... | redirect | ...`; `redirect` shape signals dissatisfaction without requiring a phrase match. Existing `select_mode` priority for `dissatisfaction` (priority 1, routes to `strategic`) stays unchanged — the classifier just sets `signals["dissatisfaction"] = True` from semantic judgment in addition to the regex path.

---

## Phase 1.5 — Classifier layer (closes Gaps 11—16)

### Architecture

Per-turn call to a fast model (Claude Haiku or GPT-4o-mini) **before** `select_mode`, run **in parallel** with regex detection. JSON output merges into the same `SessionState` accumulators. Mode-selection logic does not change — it reads totals, not detector source.

### Prompt (versioned constant `_CLASSIFIER_PROMPT_V1`)

```
You are analyzing one message from a coaching conversation.
Return JSON with these fields:

  distress_intensity: 0-3
    (0 = neutral, 1 = some difficulty, 2 = sustained difficulty,
     3 = severe distress)

  indirect_self_blame: true | false
    (does the message express that something is wrong with the user,
     even without using the words "wrong with me"?)

  escalation_from_calm: true | false
    (does this message represent emotional escalation from a
     neutral baseline?)

  request_shape: emotional_processing | action_request |
                 information_seeking | venting | redirect | social

  domains_present: [list from the tracked domains]

  weight: 0.0-1.0
    (how heavy is this message relative to ordinary conversation)

Respond with JSON only, no preamble.

User message: "{user_msg}"
```

### Integration (classifier output — SessionState)

| Classifier field | Regex equivalent | Accumulator update |
|---|---|---|
| `distress_intensity >= 2` | DISTRESS_PHRASES hit | `distress_hits += 1`; `distress_score += intensity * weight` |
| `indirect_self_blame: true` | (none — regex gap) | `distress_score += 1.0 * weight` |
| `escalation_from_calm: true` | (none) | `consecutive_distress_turns += 1` |
| `request_shape: action_request` | ACTION_REQUEST_PHRASES hit | sets `mismatch` signal candidate |
| `request_shape: redirect` | DISSATISFACTION_PHRASES hit | sets `signals["dissatisfaction"] = True` |
| `request_shape: emotional_processing` | (implicit default) | keeps `reflective` candidate |
| `domains_present` (list) | (none) | writes to `ln_conversation_arc[domain] += weight` (Phase 2) + scope gate first-K-turn density count (Phase 1) |
| `weight` (0.0—1.0) | (implicit 1.0) | multiplier on every score update |

### Cost gates

- Skip classifier on messages < 12 chars ("ok", "yes", single emoji).
- Skip on `GUEST` sessions and unauthenticated probes.
- Per-user rate limit: max 1 classifier call per 1.5 s.
- Cache identical messages within session (LRU, 16 entries).

### Failure modes

- Hard timeout 300 ms — on timeout, log `[CLASSIFIER] timeout` and fall back to regex-only (current Phase 1 behavior).
- Malformed JSON — drop classifier signals for this turn, do not raise. Log `[CLASSIFIER] parse_error`.
- Model unavailable — circuit-break for 60 s, then retry. Log `[CLASSIFIER] degraded`.

### Telemetry

- Log line: `[CLASSIFIER] user=<u> intensity=<n> shape=<s> domains=<list> weight=<w> latency_ms=<n>`
- Track classifier-vs-regex disagreement: how often classifier fires distress when regex misses (validates Gap 11 fix); how often classifier fires `redirect` when regex misses (validates Gap 16 fix). Surface to `[ADAPTIVE] disagreement_rate=<pct>` weekly.

### Rollout

Mirror scope-gate dark-launch sequence: `ENABLE_CLASSIFIER_LAYER` default `false`; deploy with flag off; 48 h shadow-log on staging; review classifier-vs-regex disagreement; enable on one staging account; flip to `true` in GREEN `.env` via `safe_deploy.sh bridge`; monitor 24 h. Regression: set `false`, redeploy — no code change.

### Alignment with existing stack

- Classifier output is **input to accumulators**, not a replacement for regex or scope gate. Regex stays as fallback when classifier is degraded/off.
- Classifier does not call Grok, sovereign LLM, or any clinical-tier inference — it is a separate utility-tier call (Haiku/4o-mini), priced and metered independently. Refund logic in `bridge_server.py` is unaffected.
- Classifier never produces user-visible text. Output is internal signal only. Nate accuracy validator is unaffected; AQ refusal/witnessing pipeline is unaffected.
- Crystal recall/crystallization unchanged: classifier signals do not get crystallized; only the user turn and Nate response do, per existing wiring.

---

## Phase 2 — Slow accumulation + cross-session policy

- Rolling topic fingerprint in **`profile_data.ln_conversation_arc`** (merge-safe with [`user_store`](backend/app/websocket/user_store.py) rules).
- Triggers when **rolling distinct topic-group count ≥ N** over **M turns** (not only first K).
- Cross-session lock policy as in Gap 8.

---

## Other Phase 1 items

- Expand **`DISSATISFACTION_PHRASES`** (pushback / “already do that” / “tried that”).
- **`ENABLE_COACHING_SCOPE_GATE`** default **`false`** (dark-launch). Rollout sequence:
  1. Deploy with flag `false` — zero user impact; `[SCOPE_GATE]` shadow-logs still emit for observation.
  2. Review staging logs for 48 h: confirm Tier 6 fires on magicguy72-class openings and is silent on single-topic sessions.
  3. Enable on one staging account; observe 3–5 sessions manually.
  4. Flip to `true` in GREEN `.env` via `safe_deploy.sh bridge`; monitor 24 h.
  5. Regression: set `false`, redeploy — no code change needed.
- Logs: `[SCOPE_GATE]` alongside `[ADAPTIVE]` (emitted regardless of flag, enabling shadow observation before activation).

---

## PR description checklist (copy-paste)

- Tier 6 **`multi_topic_clinical_opening` applies only for `turn_count <= K`** (opening-shape); **slow accumulation is not covered**: a user who surfaces the same clinical breadth across many soft turns over a longer session will not be caught by Phase 1—this is a known harm-class limitation deferred to Phase 2 arc memory.
- Gated turn semantics: state advances; **LLM only** skipped.
- Therapeutic buffer: **bypassed** for preset (Gap 7).
- No coach handoff chip for scope stabilization (Gap 10).
- Separate tickets referenced: **`SCOPE-CHAT-VAULT-AUDIT`**, **`CHAT-HISTORY-WITHIN-SESSION`**.
- **G6** turn-1 default-mode TODO remains open (Gap 4).
- **Regex layer limits documented (Gaps 11—16):** indirect distress, static thresholds, broad masking false positives, no arc memory, opening-only scope, dissatisfaction calibration lag. Phase 1 ships co-occurrence tightening (Gap 13) only; Phase 1.5 classifier layer closes the rest — deferred behind `ENABLE_CLASSIFIER_LAYER=false`.
- **Classifier (Phase 1.5) is additive:** outputs feed the same `SessionState` accumulators regex feeds; mode-selection priority unchanged; failure path = regex-only fallback.

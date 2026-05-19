# Lisa Transcript Investigation — 2026-05-19

**Scope:** Investigation only (no code changes).  
**User:** Lisa (`LetsGoLisa` per audit fixtures; transcript May 18–19).  
**Baseline reference:** r4 acceptance (`b603c5b`, 21/21) — adaptive/classifier/history-horizon work; **not** a regression target for exploratory framing behavior.

**Evidence available in repo:** Code inspection, git history since 2026-05-17, local `provider_usage.jsonl` (load-test style traffic, not tied to Lisa timestamps).  
**Evidence not available in repo:** Production bridge logs, per-turn classifier shadow payloads, full prompt assembly traces, Sentry exports for May 18–19.

---

## Issue 1: Token corruption in model output

### Instances

| ID | Local time (reported) | Symptom |
|----|------------------------|---------|
| A | May 19, 6:57 PM | English sentence with embedded Thai `ประกาศ` ("announcement") — no language switch requested |
| B | May 19, 7:27 PM | `a_secure attachment issue` (likely intended "an insecure attachment issue"); underscore artifact |

### Root cause hypothesis

**Primary (Instance A):** Garble-detection gap — Thai script is not classified in streaming/sentence sanitizers, so a single foreign-script token can pass through to the client.

**Primary (Instance B):** High decoding temperature + exploratory-mode prompt pressure — not transport corruption. Likely model word-choice / subword-boundary glitch or mistaken markdown-style emphasis, not classifier JSON failure.

**Secondary:** Post-stream sanitization runs after the user may already have seen streamed tokens; mild corruption below detection thresholds is not rewritten live.

### Evidence

#### Decode parameters (May 17 → present)

| Location | Parameters | Change since May 17? |
|----------|------------|----------------------|
| `nate_ai_config.nate_temperature()` | Gaussian ~1.37 (std users), up to ~1.56 (elevated cohort) | **No commit changes** to this file in the window |
| `sovereign_chat_client._stream_grok` / `_stream_azure` / `_stream_workers_ai` | `temperature` + `max_completion_tokens` / `max_tokens` only | **No** `top_p`, `presence_penalty`, or `frequency_penalty` anywhere in streaming payloads |
| `bridge_server.py` inference | `_user_temp = nate_temperature(profile.get("username"))` passed to sovereign stream (~9223) | Same pattern pre/post r4 |
| `little_nate_classifier._call_classifier_llm` | `temperature: 0.0`, `max_completion_tokens: 200`, `response_format: json_object` | Isolated from chat generation; r3+ hardening intact |

**Elevated-temperature cohort** (`nate_ai_config.py` ~42–47): `sweet2noend`, `client_wilsnaw`, `FAM_5D6AC5DF` — **`LetsGoLisa` is not in the cohort**; she still gets ~1.1–1.52 standard band.

#### Fallback path divergence

| Path | Temperature | Garble handling |
|------|-------------|-----------------|
| Primary stream (`generate_streaming`) | `_user_temp` (~1.37) | Real-time `is_chunk_garbled` in `bridge_server.py` ~9267–9277 |
| Garble abort fallback (`generate_complete`, odpe `TENSION`) | Same `_user_temp` | **No** chunk-level garble check on fallback text |
| Race fallback (`inference_race.py`) | Passed through (~1.37) | No garble layer in race module |

Fallback does **not** use different decode knobs; it can still emit corrupted text if sanitizers miss it.

#### Garble sanitizer blind spot (Instance A)

`response_sanitizer.py`:

- Script tags in `is_chunk_garbled`: Cyrillic, CJK, Hangul, Arabic, Latin — **no Thai (U+0E00–U+0E7F)**.
- `_MIXED_SCRIPTS` regex: Cyrillic/CJK/Korean/Arabic pairs — **no Thai**.
- Per-sentence `_is_garbled`: flags if >30% of **words** are non-ASCII; one Thai word in a long English sentence often stays **below** threshold.
- Streaming gate: `is_chunk_garbled` needs `score >= 3`; one Thai word in a mostly-ASCII chunk often scores 0–2.

Commit `0307714` (May 18) expanded garble detection (all providers, Hangul/Arabic, code tokens) — **did not add Thai**. This matches Instance A surviving the Kristy-era fix.

#### Instance B (`a_secure`)

- Not matched by `_GARBLE_TOKENS`, `_UNDERSCORE_PREFIX` (`^_[A-Z]`), or code-token heuristics (`a_secure` is short).
- Consistent with **semantic** output under exploratory addendum ("offer 2-3 specific hypotheses") at high temperature, not JSON repair bleed (classifier uses separate HTTP call, temperature 0).
- r3 classifier fix (`json_parse_failed` does not open circuit; retry with strict prompt) — **still present** at `little_nate_classifier.py` ~347–351, ~319–332. Unlikely related to chat token text.

#### Context window / `_SP_CAP` (Instance A & B)

- `_SP_CAP = 32000` chars; trim logs `[PROMPT CAP]` when exceeded (`bridge_server.py` ~9139–9141).
- r4 added live-turn buffer (16) + critical recall facts — increases prompt size but **far below** 32k char cap for typical sessions.
- Local `provider_usage.jsonl` shows Grok clinical calls at **~1.4–1.6k tokens in** (May 19 04:18 UTC) — not near cap.
- **Cannot confirm** `[PROMPT CAP]` for Lisa at 6:57 PM / 7:27 PM without production logs.

#### Classifier / r3 regression check

- Parse failures return `ClassifierResult(error="json_parse_failed")` without opening circuit (~347–351).
- Classifier output does **not** get concatenated into user-visible reply; it only merges signals into adaptive state (`bridge_server.py` ~9078–9082).
- **Confidence:** Classifier retry path is **unlikely** cause of visible chat corruption.

#### Delivery order

Streaming sends deltas to the client **before** final `sanitize_response` (`bridge_server.py` ~9294 vs ~9578–9584). Sanitizer can only correct on a **second** send if text changed; subtle single-token corruption may be user-visible either way.

### Severity

| Instance | Severity | Rationale |
|----------|----------|-----------|
| A (Thai token) | **Medium** | Breaks immersion/trust; not safety-critical; indicates monitor gap |
| B (`a_secure`) | **Low–Medium** | Clinical mis-framing overlap with Issue 2; readability/accuracy issue |

### Recommended fix scope (do not implement here)

1. **Sanitizer:** Add Thai (and optionally all non-Latin scripts used in production) to `is_chunk_garbled` script set; treat isolated non-Latin tokens in Latin sentences as garble.
2. **Sanitizer:** Sentence-level rule: any word in Thai/Devanagari/etc. in predominantly English assistant output → strip or trigger regen.
3. **Optional:** Lower chat temperature for clinical domain (e.g. cap at 1.0–1.2) or A/B — separate from garble.
4. **Garble fallback:** Run `sanitize_response` on fallback complete text; consider regen if foreign script detected.
5. **Observability:** Log `[GARBLE]` + provider + uid + turn_id; metric for non-ASCII ratio in final response.

### Confidence

| Hypothesis | Confidence |
|------------|------------|
| Thai = sanitizer coverage gap | **High** |
| `a_secure` = high temp + model glitch, not classifier JSON | **Medium** |
| Context overflow / `_SP_CAP` trim caused either | **Low** (needs logs) |
| r3 classifier regression caused either | **Low** |
| Fallback path used different decode params | **Rejected** (code shows same temperature) |

### Additional data needed

- Production `docker logs nate_bridge` for `LetsGoLisa` hardware_id around **2026-05-19 22:57–23:27 UTC** (if user times are US Eastern) with: `[GARBLE]`, `[PROMPT CAP]`, `[SOVEREIGN] Provider`, `[ADAPTIVE]`, `[CLASSIFIER]`.
- `conversation_history` rows for those turns (full `ai_text`).
- Whether `ENABLE_CLASSIFIER_LAYER` / `ENABLE_COACHING_SCOPE_GATE` / `ENABLE_ARC_MEMORY` are true on GREEN.
- Sentry/issues search: `GARBLE`, `json_parse_failed`, `foreign`, `sanitize`.

---

## Issue 2: Clinical concept introduction without scope gate

### Incident

**May 19, ~7:27 PM:** Nate offered `a_secure attachment issue` as one of three framings for overcommitment on a hot, sleep-deprived day. User had not used attachment language. Nate later expanded into "internalized harsh parent figure" and "protective strategy from past experiences."

User turn at 7:27 PM was **not** expected to trigger scope gate (scheduling/overcommit content).

### Root cause hypothesis

**Primary:** **Scope-gate coverage gap + exploratory mode addendum** — gate is user-input-only and (by default) dark-launched; exploratory mode **instructs** the model to produce 2–3 clinical-style hypotheses without forbidding unsolicited diagnostic labels.

**Not primary:** Classifier routing miss for this turn (classifier shapes accumulators, not exploratory vs reflective directly).

**Possible contributor:** Crystal / PG history / prior-session context priming attachment or family-of-origin themes — **unverified** without prompt trace.

### Evidence

#### Scope gate is user-input-only

`little_nate_coaching_scope_gate.evaluate_scope_gate()` (~217–223) scores **only `user_msg`**. No parameter for assistant draft or planned output.

Topic groups (`CLINICAL_TOPIC_KEYWORDS`, ~37–133) include marital, grief, trauma, shame, etc. — **no `attachment` / `attachment_theory` group**. User message about overcommit/sleep would not match ≥4 groups for opening gate.

`ENABLE_COACHING_SCOPE_GATE` defaults **`false`** (`little_nate_coaching_scope_gate.py` ~29–31). Even when gate matches, `prepare_response` only returns `direct_response` if flag enabled (`little_nate_adaptive.py` ~562–577). Otherwise **`[SCOPE_GATE]` shadow logs only** — LLM still runs with full addendum.

**Expected for 7:27 PM user turn:** Gate does **not** fire (correct per design). Stabilization template would **not** have appeared unless flag on + multi-topic opening — neither applies.

#### Exploratory addendum explicitly requests clinical framings

`little_nate_adaptive.py` `MODE_ADDENDA["exploratory"]` (~384–390):

- Instructs: "offer **2-3 specific hypotheses or framings**"
- Forbids reflective phrases (`what's coming up for you`, `I sense`, etc.)
- **Does not** forbid attachment theory, diagnostic labels, or "insecure/secure attachment"
- Ends with: ask which framing fits

This is **aligned with r4 acceptance** (exploratory mode for action/mismatch turns) and **conflicts** with unsolicited clinical interpretation policy.

#### Mode selection for overcommit / sleep-deprived day

`select_mode` priority (~288–364): dissatisfaction → accommodating/neuro → distress → **mismatch** → rut → keep mode.

`detect_mode_mismatch` (~230–244): requires `ACTION_REQUEST_PHRASES` in **user** message + recent assistant reflection pattern. User discussing overcommit **may** match action language (`help me`, `what should I`, etc.) from earlier turns; if session already in **exploratory**, subsequent turns **keep** exploratory unless higher-priority signal fires.

**No bot-output guard** before LLM. Scope gate does not run on assistant text.

#### Classifier role (7:27 PM)

`classify_message` returns `request_shape`, `domains_present`, `weight`, etc. (`little_nate_classifier.py` ~75–104).

Valid shapes include `emotional_processing`, `action_request`, … — **classifier does not select exploratory vs reflective**.

`merge_classifier_into_state` (~444–493) updates distress accumulators; optional `ENABLE_CLASSIFIER_LAYER` handoff at score ≥4.5 — unrelated to attachment framing.

`family_of_origin` is a valid classifier domain — if present in shadow logs, arc could accumulate (`little_nate_arc_memory.py` ~56–57 maps to `parenting_family`) but **`ENABLE_ARC_MEMORY` defaults false** — arc-triggered stabilization unlikely unless enabled on server.

#### Post-generation checks

- **Layer 8** (`nate_response_validator.py`): `unverified_factual_assertion_about_person` — targets false claims about **real people**, not hypothetical clinical framings.
- Diagnosis regex (~382) targets explicit "I diagnose / your diagnosis is" — **not** "attachment issue" hypothesis language.
- **No** rule blocking unsolicited attachment/psychodynamic labels.

#### Prompt priming (unverified)

`process_interaction` parallel prefetch (~8321–8328): relational context, crystals (`recall_crystals_for_context`), PG history (15 rows), live turns (16), critical recall facts (r4).

Any of these **could** contain attachment/family-of-origin language from prior sessions. **Cannot confirm** for 7:27 PM without logged prompt length and crystal text.

`[PROMPT CAP]` truncation could drop guardrails at end of prompt while keeping middle context — **low probability** at ~1.5k tokens in (provider_usage proxy).

#### r4 regression flag

| Question | Assessment |
|----------|------------|
| Did r4 break scope gate? | **No** — scope gate unchanged in r4 commits |
| Did r4 cause attachment framing? | **Indirectly by design** — r4 strengthened exploratory/handoff and history; more context may increase psychodynamic vocabulary |
| Is this a failed acceptance criterion? | **Product/policy gap**, not a 21/21 test failure — acceptance tests likely did not forbid unsolicited attachment labels in exploratory mode |

### Severity

**Medium** (clinical boundary / trust). User engaged willingly; not crisis. Risk scales on more vulnerable users or coach-visible transcripts.

### Recommended fix scope (do not implement here)

| Approach | Pros | Cons |
|----------|------|------|
| **A. Mode addendum tightening** (exploratory/strategic) | Small diff; fast | May reduce usefulness of framings |
| **B. Bot-output guardrail** (post-gen or pre-send) | Catches all modes | New layer; latency |
| **C. Scope gate expansion** (assistant-side or "clinical label without user vocabulary") | Reuses stabilization pattern | Needs clinician copy; may over-block legitimate psychoeducation |
| **D. Prompt-level** ("do not introduce attachment/diagnosis unless user named it") | Cheap | Soft compliance at high temperature |

**Recommendation:** Combine **A + D** short-term (addendum + base prompt rule); plan **B** for Layer 8-style validator extension (`unsolicited_clinical_framing`) medium-term. Scope gate expansion (**C**) only if product wants hard block → stabilization, not soft instruction.

**Do not** rely on user-only scope gate for this failure mode.

### Confidence

| Hypothesis | Confidence |
|------------|------------|
| User-only scope gate + exploratory addendum = expected behavior | **High** |
| ENABLE_COACHING_SCOPE_GATE off on production | **Medium** (env not in repo; default false) |
| Classifier mis-routed to exploratory | **Low** (classifier doesn't pick mode) |
| Crystal/history primed attachment | **Medium–Low** (needs prompt dump) |

### Additional data needed

- `[SCOPE_GATE]` and `[ADAPTIVE] mode=... signals=...` log lines for 7:27 PM turn.
- Classifier shadow: `domains_present`, `request_shape`, `weight` for that user message.
- Redacted system prompt slice (addendum + last 2k chars of base) for that turn.
- Prior 3 assistant messages (confirm exploratory lock-in).
- `skyeye_activity` / factual grounding rows if Layer 8 fired.

---

## Issue 3: Mild rut on low-weight content (lower priority)

### Incident

**May 19, 7:34 PM and 7:35 PM:** User: "I'm taking a nap" / "Practical step to restore resources. Bye for now."  
Both replies got **three-framing exploratory** treatment with near-identical framings.

### Root cause hypothesis

**Primary:** **`detect_assistant_rut` is built for reflective-loop detection**, not exploratory framing repetition. Exploratory responses avoid banned reflection phrases, so rut never fires; session stays in exploratory.

**Secondary:** **No closing-turn / low-weight turn detector** — classifier exposes `weight` and `request_shape: social` but mode selection ignores them.

### Evidence

#### Rut detector logic (`little_nate_adaptive.py` ~252–259)

Fires only when **all** of:

1. Last **3** assistant messages exist
2. **All three** end with `?`
3. At least **2** of those contain `REFLECTION_TELLS` (`coming up for you`, `behind your words`, `I sense`, `I hear`, `it sounds like`)

Exploratory three-framing replies typically:

- End with a "which fits?" question → satisfy (1) and (2)
- Use concrete hypotheses, **not** reflection tells → fail (3)

So **repeated exploratory menus do not count as a rut** — by construction.

`select_mode` then (~359–362): rut → exploratory, but rut **never true** for this pattern.

#### No message-weight gating in mode selection

Classifier returns `weight: 0.0–1.0` (`little_nate_classifier.py` ~99–100).

`merge_classifier_into_state` records domains/distress — **does not** pass `weight` into `select_mode`.

No patterns for: `bye`, `goodbye`, `nap`, `signing off`, `talk later` in adaptive mode logic.

`request_shape: social` exists in classifier schema (~91) — **not consumed** for mode downgrade to reflective/acknowledgment.

#### Mode lock-in

Once in exploratory (often via earlier mismatch/action request on overcommit thread), `select_mode` default branch (~363–364) **keeps** exploratory until dissatisfaction, accommodating, distress, or rut (ineffective) fires.

Closing messages are low signal but **do not** switch mode.

#### r4 regression flag

**Not an r4 regression.** Rut detector unchanged in r4. Exploratory mode was **introduced/enhanced** in adaptive work — three-framing on exit turns is a **known gap**, not a break from 21/21.

### Severity

**Low** — UX polish / tone at session end. User was leaving; redundant framings are awkward, not harmful.

### Recommended fix scope (smallest change)

| Option | Change | Fits case? |
|--------|--------|------------|
| **1. Closing-turn detector** (preferred) | If user message matches `CLOSING_PHRASES` or classifier `social` + low `weight`, force **reflective** one-liner (acknowledge + warm close); suppress exploratory addendum | **Yes** — directly addresses nap/bye |
| **2. Rut detector v2** | Extend rut to detect similar **structure** in last 2 assistant msgs (e.g. "One:" / "Another:" / numbered framings) | Helps repeat menus, not only closings |
| **3. Classifier weight threshold** | If `weight < 0.25`, never attach exploratory addendum | Broader; may miss light but real topics |

**Recommendation:** **#1** smallest targeted fix; add **#2** if product wants anti-repetition across exploratory turns.

### Confidence

| Hypothesis | Confidence |
|------------|------------|
| Rut detector cannot fire on exploratory repeats | **High** |
| No closing-turn handling | **High** |
| Classifier weight unused in mode selection | **High** |

### Additional data needed

- Last 3 `recent_assistant_msgs` from adaptive state at 7:34 PM (confirm no reflection tells).
- `[ADAPTIVE] mode=exploratory signals=...` for 7:34 and 7:35 PM.

---

## Cross-cutting notes

### Production flags (verify on GREEN)

| Flag | Default | Effect if false (typical prod) |
|------|---------|------------------------------|
| `ENABLE_COACHING_SCOPE_GATE` | false | Multi-topic stabilization **not** enforced |
| `ENABLE_CLASSIFIER_LAYER` | false | Classifier shadow only; handoff score still accumulates in shadow path partially |
| `ENABLE_ARC_MEMORY` | false | Arc-based stabilization **not** enforced |

Lisa's session behaving "well" on recall/exploratory is **consistent** with r4 dark-launch + successful context injection.

### Kristy garble fix (May 18) vs Lisa Instance A

Same class of issue (foreign/script pollution) but **different script**: Kristy fix added Korean/Arabic/code tokens; Thai remains unmonitored. Lisa A is **not** evidence the May 18 fix failed globally — it evidence **incomplete script coverage**.

### Sentry / 72h corpus

**Not queried** in this pass (no API access). Recommend: search production error tracker for `GARBLE`, `json_parse_failed`, `sanitize`, non-ASCII, May 17–19.

---

## Summary table

| Issue | Likely cause | Fix lane | Confidence |
|-------|--------------|----------|------------|
| 1A Thai token | Garble sanitizer missing Thai | `response_sanitizer.py` + metrics | High |
| 1B `a_secure` | High temp + model glitch; not classifier | Temp cap and/or post-gen word check | Medium |
| 2 Attachment framing | User-only scope gate + exploratory addendum | Addendum + output guardrail | High |
| 3 Nap/bye framings | Rut definition + no closing-turn mode | Closing-turn detector in adaptive | High |

---

*Investigation completed from codebase state at `b603c5b` (r4). No patches applied.*

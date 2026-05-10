# Little Nate — prompt delivery architecture (read-only audit)

Date: 2026-05-06. Scope: `AzureCortex.process_interaction` client path in `backend/app/websocket/bridge_server.py`, Observer build, post-generation hooks.

---

## 1. SYSTEM_PROMPT POSITIONING (CLINICAL EDGE)

**Assembly order (start → end):**  
`build_llm_time_context` → static identity / liminal / resilience blocks → `{relational_context}` → USER PROFILE / ACCUMULATED WISDOM / `{crystal_context}` / `{vault_context}` / workbook / DOJO flag → **CONVERSATION MEMORY** + pg history → sanctuary / checkin → web + deep-memory blocks → IP boundary → **GUIDELINES** (incl. FACTUAL GROUNDING, RESPONSE LENGTH, SESSION ISOLATION) → **CLINICAL EDGE** (`~8709`) → PRIORITY OVERRIDES → METAPHOR / LINGUISTIC BAN / ETHICAL COMPLEXITY → YOUR LIMITATIONS → `{observer_context}` `{evocative_context}` `{drift_context}` `{reply_context}` `{lr_context}`.

**CLINICAL EDGE vs start:** The block is **not** near the beginning of the delivered string. All expandable history (memory, crystals, wisdom, vault, sanctuary, etc.) is **inserted before** the literal `GUIDELINES:` header; CLINICAL EDGE is **after** that bulk.

**Static template only (Python source, unexpanded):** From `system_prompt = f"""{_time_ctx}` through the line before `CLINICAL EDGE (Use when the client is ready):` is **~12 558** characters; full f-string through `{lr_context}"""` is **~23 768** characters → **~53%** of that *static* span is before CLINICAL EDGE. Dynamic inserts **before** GUIDELINES typically dominate total size, so in **assembled** prompts CLINICAL EDGE usually falls in the **middle-to-last portion** of the document (often **last ~25–50%** of tokens when history is large—not first 25%).

**Typical token count:** Not logged as tokens. Code prints `>>> [SYSTEM PROMPT] {len(system_prompt)} chars` (`~8853`). Rule-of-thumb: **chars ÷ ~4 ≈ tokens** (English). **Cap:** `_SP_CAP = 32000` chars; overflow **truncates the end** of the assembled string (`~8850–8852`), which can cut trailing sections (including injected tails) on very long prompts.

**Completion budget:** Primary paths use **`max_tokens=1500`** (`~8898`, `~9036`, fallbacks similar), which allows outputs **far longer** than 2–4 sentences.

---

## 2. OBSERVER PROTOCOL & CLINICAL EDGE READY

**Grep targets:**  
- Phrase **“CLINICAL EDGE READY”** and observer injection: `bridge_server.py` **~8314–8321** (build), **~8716** (static guideline cross-reference), **`{observer_context}`** at **~8843**.  
- **“OBSERVER PROTOCOL (MANDATORY):”** appended inside **`observer_context`** when non-empty: **~8337–8347**.

**Where computed:** `AzureCortex.process_interaction`, block **`# === OBSERVER PROTOCOL ===`** (`~8250–8353`). Reads `self.metrics.load_metrics(profile)` → `nevedal_state` (`crisis_perception`, **`shame_profile` → `sp`**, **`pmb`**).

**CLINICAL EDGE READY conditions** (`~8305–8321`, inside `pmb` dict branch):  
- `recon = pmb.get("reconsolidation_readiness", 0)`  
- `shame_idx = sp.get("shame_index", 0)` (from `shame_profile`)  
- **Intellectualization flag:** `deflection > 0.20` and `self_blame < 0.15` and `shame_masking_pattern` in `("WITHDRAWAL_MASKED", "UNKNOWN")`.  
- **Fires if:** `(recon > 0.6 and shame_idx < 0.4) **or** (recon > 0.4 and _intellect_detect)`.

**Wiring:** **Not orphaned.** `observer_context` is part of the same `system_prompt` f-string; log: `>>> [OBSERVER PROTOCOL] Injected {len(observer_context)} chars`. Static text at **~8716** explicitly tells the model to shift when **Observer Protocol** signals **CLINICAL EDGE READY** (aligned with injected line when conditions met).

---

## 3. RESPONSE LENGTH ENFORCEMENT

**Guideline only:** `RESPONSE LENGTH: Keep responses to 2-4 sentences` at **~8690** (soft instruction).

**Post-generation:** **No** sentence-count or 2–4-sentence enforcement in `process_interaction`. Post-steps include: strip `redacted_thinking`, **`sanitize_ai_response`**, **`sanitize_response`**, **Layer 8** `validate_before_send` (factual assertion / Layer 8—see `response_validator_bridge.py`) (**~9200–9215**), Queens Guard L3 (**~9217+**). None of these implement the 2–4 sentence rule.

**Log sampling (5 conversations, anonymized word counts):** **Not performed.** No bridge/chat transcripts in-repo under `*.log`. Would require `docker logs nate_bridge`, exported `conversation_history`, or captured `[SOVEREIGN] ... len=` / replay from staging.

**Expectation vs rule:** **`max_tokens=1500`** and long-context completions **do not mechanically enforce** brevity; empirical alignment with 2–4 sentences would require telemetry or DB sampling.

---

## Evidence refs (line numbers, `bridge_server.py` unless noted)

| Topic | Location |
|-------|----------|
| `system_prompt = f"""` start | ~8591 |
| GUIDELINES / RESPONSE LENGTH | ~8662–8690 |
| CLINICAL EDGE block | ~8709–8739 |
| `{observer_context}` | ~8843 |
| `_SP_CAP` trim | ~8848–8852 |
| `max_tokens=1500` streaming | ~8898 |
| Post-send `validate_before_send` | ~9201–9215 |
| CLINICAL EDGE READY build | ~8313–8321 |

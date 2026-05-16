# Capacity ground truth — supplement (2026-05-15)

**Provenance:** `audit/capacity_ground_truth_<DATE>.md` was **not present** in this workspace at authoring time. This file contains **Phase 4** and **Phase 3b** plus **§5 / §6 patch blocks** to merge into your existing report if that file lives outside the repo.

---

## Phase 4: Chat hot path trace (code inspection only)

**Scope:** Inbound `chat_message` → `AzureCortex.process_interaction` through response emission and post-send hooks. Citations: `backend/app/websocket/bridge_server.py` unless noted.

| Step | File:Line | What it does | PG connection held? | Awaited before WS send? | Notes |
|------|-----------|--------------|---------------------|-------------------------|-------|
| 1 | `bridge_server.py:12304-12308` | WebSocket `chat_message`: requires `current_profile`; calls `cortex.process_interaction(..., client_context=getattr(websocket, "_eviction_context", "main"))`. | No | Yes (handler awaits full `process_interaction`) | User/session identity is `current_profile` (post-login bridge state), not re-resolved here. |
| 2 | `bridge_server.py:8105-8112` | `process_interaction` entry: `uid = profile.get("hardware_id")`; `_ctx` / `_turn_id` for scoped sends. | No | Yes | |
| 3 | `bridge_server.py:8127-8131` | IP boundary check; may `_send` and **return**. | No | Yes (early send) | |
| 4 | `bridge_server.py:8141` | `billing.use_tokens(...)` | No *in synchronous deduct path* | Yes | `use_tokens` (`bridge_server.py:5971-6025`) mutates registry + `save_registry`; if `db_pool` on billing, schedules `create_task(_atomic_deduct)` and `create_task(_report_meter_usage)` — **not awaited** by caller. |
| 5 | `bridge_server.py:8154-8155` | `analytics.record_event` | No | Yes | |
| 6 | `bridge_server.py:8160-8163` | Sync `memory_context` / `wisdom` / `family_context` / `sanctuary_context` (memory + local/vault helpers, not PG in this snippet). | No | Yes | |
| 7 | `bridge_server.py:8164-8181` | **`asyncio.gather`**: `_get_relational_context`, `_get_checkin_context`, `recall_crystals_for_context(_cpool, ...)`, `_fetch_pg_history_for_chat(_cpool, ...)` with `_cpool = chat_db_pool or db_pool`. | **Yes — up to 4 concurrent connections** (one per task that hits PG), each via `async with pool.acquire()` inside helpers | Yes | **Parallel.** Relational + checkin use **`db_pool`** (`7848-8002`, `7987-7996`). Crystals + pg history use **`_cpool`** (`8176-8180`). Pool sizes: main `max_size=40`, chat `max_size=8` (`29965-29983`). |
| 8 | `crystal_recall_bridge.py:303-318` | `recall_crystals_for_context`: `acquire`, user lookup, `_fast_recall_crystals(conn, ...)`. | Yes, for duration of that `acquire` block | Yes | After release: `create_task(_reinforce_recalled_crystals)` + `create_task(_deep_recall_crystals)` (`356-358`) — **fire-and-forget**, not awaited before send. |
| 9 | `bridge_server.py:6979-6988` | `_fetch_pg_history_for_chat`: `conversation_history` SELECT. | Yes | Yes | |
| 10 | `pg_data_helpers.py:832-840` | `get_classroom_context_for_client_pg`: `classroom_session_analyses` SELECT (from `_get_relational_context`). | Yes | Yes | Called from relational path when `story_path` exists or early branch; may combine with file `story.json`. |
| 11 | `bridge_server.py:8025-8032` | `_get_assessment_context`: quiz submissions SELECT. | Yes | Yes | Awaited inside `_get_relational_context` when story exists (`7971`). |
| 12 | `bridge_server.py:8185-8280` | Web search: may `await search_proxy.execute_search`, `await _send`, consent `await ws.send` — external HTTP / WS, not PG. | **No (in `search_proxy.py`)** | Yes | Shell: `grep -E 'db_pool|acquire' backend/app/services/search_proxy.py` → **no lines**, `grep_exit=1` (2026-05-15, repo root). |
| 13 | `bridge_server.py:8288-8294` | `_deep_memory_search_chat` when trigger fires. | Yes (multiple short `acquire`s in parallel subtasks) | Yes | `7107-7222`: `gather` of FTS + crystal ILIKE + `recall_crystals_for_context` + vector path; `_search_vec` uses `acquire` then `semantic_search_all` (network). |
| 14 | `bridge_server.py:8298-8557` | Observer / evocative / drift / reply therapy context: `self.metrics.load_metrics` — **vault/metrics files**, not PG in traced calls. | No | Yes | |
| 15 | `bridge_server.py:8579-8624` | Optional vault: `db_pool.fetchrow` on `vault_items`. | Yes | Yes | |
| 16 | `bridge_server.py:8628-8635` | Liminal Resolve `get_context_injection(user_text, memory_context, observer_context, uid)` | **Yes** — uses engine `self._db_pool` | Yes | Engine: `liminal_resolve_engine.py:210-287` — `await self._load_state(user_id)` → `async with self._db_pool.acquire()` at `665-670`; optional `await self._db_pool.execute(... parts_detection_feedback ...)` at `256-266` (**`session_id` is referenced in SQL but not a parameter of `get_context_injection`** — insert is in `try/except: pass`, likely no-op / exception). |
| 17 | `bridge_server.py:8637-8937` | Assemble `system_prompt` (string); cap at 32000 chars (`8933-8936`). | No | Yes | |
| 18 | `bridge_server.py:8939-8948` | Queens Guard `sanitize_input` (CLIENT). | **Conditional** | Yes | `queens_guard.py:436-534` — in-memory checks; **if flags**, `await self._persist_sanitization_event` → `async with self.db_pool.acquire()` at `1062-1063`. Bridge sets `_queens_guard.db_pool = db_pool` at `bridge_server.py:29993-29994`. |
| 19 | `bridge_server.py:8961-8968` → `therapeutic_controller.py:671-875` | `prepare_therapeutic_context`: identity resolve, `evaluate_disclosure`, `_classify_tmc`, narratives, optional neuro crystals, cap resolver paths — all may `await` DB helpers with passed `db_pool`. | Yes (multiple short `acquire`s via helpers, not one span) | Yes | Example awaits: `resolve_username` (`704-708`), `_scb.evaluate_disclosure` (`734-740`), `_classify_tmc` (`747`), `_fetch_recent_narratives` (`792`), `_recall_neuroscience_crystals` (`794-795`), `_resolve_predictability_continuity_cap` (`810-815`). |
| 20 | `bridge_server.py:8980-8982` | If TMC audit active: `await self._send_nate_thinking(...)`. | No | Yes | UX “thinking” message before provider stream. |
| 21a | `bridge_server.py:8989-9120` | **Primary:** `_USE_SOVEREIGN_ROUTING and _sovereign_stream` → `async for delta, provider in _sovereign_stream(...)`. | **No** — inference in `sovereign_chat_client.py` (HTTP/WS to providers only) | **Partial:** streaming `await self._send` inside loop when chunk buffer ready (`9081`, `9102`, `9117`, etc.) | Garble retry may `await generate_complete` (`9091-9097`). |
| 21b | `bridge_server.py:9126-9140` | Elif `_sovereign_generate` | No | Yes (full response then later emit) | |
| 21c | `bridge_server.py:9141-9157` | Elif `_race_inference` → `inference_race.race_inference` | No | Yes if `send_fn` streams Azure deltas | |
| 21d | `inference_race.py:141-158` | **Race:** `asyncio.wait(..., FIRST_COMPLETED)`; **cancel** pending; `await` cancelled tasks. | No | **Azure path** may `await send_fn(uid, full_response)` on deltas (`113-114`) | **No PG** in race module. Losers are HTTP/WS only; no pool lease to release. |
| 21e | `bridge_server.py:9160-9185` | Else Azure realtime-only fallback loop with inline `_send`. | No | Yes | |
| 22 | `bridge_server.py:9187-9248` | AQ refusal retry / witnessing fallback | Depends on branch | Yes | May call `_sovereign_generate` or `_race_inference` again. |
| 23 | `therapeutic_controller.py:925-1002` | **`await audit_therapeutic_response`** | Yes — `_log_audit` uses `async with db_pool.acquire()` (`1029`) | Yes — runs **before** `_emit_after_inference` at `9264` | Additional **LLM** retry possible via `chat_completion_with_fallback` (`972`). |
| 24 | `bridge_server.py:9264-9266` | `await self._send(uid, full_response, ...)` if not already streamed (or buffered audit). | No | Yes | |
| 25 | `bridge_server.py:9289-9303` | `INSERT odpe_signal_log` with `async with db_pool.acquire()` | Yes | Yes — **after** step 24 | |
| 26 | `bridge_server.py:9316-9344` | Sanitize / optional extra `_send`; Layer 8 `await _validate_factual` may `await _send` redirect. | **Usually no PG** on redirect path | Yes | `response_validator_bridge.py:35-95`: awaits `_validator.log_warnings` only when caller `db_pool` set (`86-87`), but module `_validator` is `NateResponseValidator()` with default `db_pool=None` (`19`). `log_warnings` returns immediately if `not self.db_pool` (`nate_response_validator.py:633-634`). **PG logging for Layer 8 not observed** with current bridge wiring unless another initializer sets `\_validator.db_pool`. |
| 27 | `bridge_server.py:9348-9359` | Queens Guard L3 `verify_output` may `await _send`. | **Conditional** | Yes | `queens_guard.py:870-1000` — pattern-only checks; **if `blocked`**, `await self._persist_redaction_event` → `async with self.db_pool.acquire()` at `1089-1090`. |
| 28 | `bridge_server.py:9362-9365` | **`await _lr_engine.evaluate_response(..., db_pool, uid)`** + **`await _lr_engine.post_response_update(...)`** | **Yes — separate short `acquire`s** | Yes — **after** prior sends | `evaluate_response` may call `_load_state` / regenerations (`293-354`); `post_response_update` → `_load_state` + `_save_state` → `async with self._db_pool.acquire()` at `670` and `711` (`665-711`). |
| 29 | `bridge_server.py:9369-9417` | `memorize`; **`asyncio.create_task(crystallize_from_conversation)`**; session summary task; **`asyncio.create_task(_persist_chat_to_conversation_history)`** | No in caller | **No** — fire-and-forget | |
| 30 | `bridge_server.py:9437-9445` | `UPDATE users SET last_nate_message_at` with `async with db_pool.acquire()` | Yes | Yes — still before handler returns | |
| 31 | `bridge_server.py:9480-9483` | `await self._send_metrics_update` | No (WS only to client) | Yes | |

### Flags (code-backed)

- **PG held across inference:** **Not observed** as a single long-lived `acquire` wrapping the streaming generator. Reads use short `acquire` scopes; inference runs in `sovereign_chat_client` / aiohttp without `db_pool` in those functions.
- **Writes awaited before WS send that could be deferred:** **Therapeutic audit** (`9251-9261`) and **ODPE signal log** (`9289-9305`) run **after** streaming sends for the main body but **before** later sanitization sends; audit is explicitly **before** `_emit_after_inference` when buffering (`9263-9266`). **Liminal post-response** (`9362-9365`) runs **after** multiple possible `_send` calls — **latency extension** on the path to handler completion.
- **Same connection read+write one turn:** Not observed as one `acquire` spanning both; multiple separate `acquire`s per turn.
- **Missing `acquire` / leak risk:** Traced helpers use `async with db_pool.acquire()`. Queens Guard / LR engine use scoped `acquire`. **Layer 8** `log_warnings` uses `acquire` only if module-level validator has `self.db_pool` set (`nate_response_validator.py:646`); bridge import leaves it **unset** (`response_validator_bridge.py:19`, `633-634`).

### Estimated PG connection-hold (synchronous `process_interaction` path)

- **Pre-inference:** Dominated by **wall time of `asyncio.gather`** for relational/checkin/crystal/pg_history (each holds its own connection overlapping in time) **plus** sequential awaits: vault row, deep search (if triggered), `prepare_therapeutic_context`, etc. Exact seconds: **UNVERIFIED** (no timing logs captured in this audit).
- **During inference:** Pool not held for streaming path per code above.
- **Post-first-final-send:** Additional **awaited** PG: `odpe_signal_log`, `last_nate_message_at`, therapeutic audit’s `_log_audit` (ordering: audit before emit-after-inference; ODPE after). LREngine awaits may touch PG **after** user-visible correction sends.

**Concurrency note:** User asked `40 / X` with `pool max_size=40`. Code documents **main pool `max_size=40`** and **chat context pool `max_size=8`** (`29965-29983`). Chat-scoped reads use **`chat_db_pool` when configured**, so the binding pool for the 4-way gather is often **`max_size=8`**, not 40 — **sustained concurrent turns** can queue on `chat_db_pool` earlier than on the main pool.

**Formula (illustrative only):** If average hold time per **chat_pool** checkout in the gather is **X** seconds and four tasks run, expected peak chat pool demand ≈ **4 concurrent** holds per turn during that window ⇒ plan for **`chat_db_pool` contention`** when many turns overlap; main pool still serves therapeutic/vault/liminal/audit paths in parallel.

---

## Phase 3b: Inference provider limits (live console pull)

**Status:** **UNVERIFIED — console access required** for TPM/RPM/concurrency from x.ai, Azure Portal, Anthropic, Cloudflare, and Hetzner/Ollama dashboards. **No production log grep was run** from this workspace (no SSH / log path provided in task context).

### Providers wired for text chat (code)

| Path | Module | Providers |
|------|--------|-----------|
| Default ODPE routing ON | `bridge_server.py:196`, `8989-9007`; `sovereign_chat_client.py:310-337` | Ordered try chain: **workers_ai → grok → sovereign → azure** (exact primary from `_resolve_provider_for_signal` + `_first_configured`). |
| Race fallback (when used) | `inference_race.py:125-183` | **Grok** HTTP (`NATE_CHAT_URL`) vs **Azure Realtime** WS (`AZURE_OPENAI_ENDPOINT` + `AZURE_OPENAI_DEPLOYMENT`). |

### Quota table

| Provider | Account / Deployment | TPM limit | RPM limit | Concurrent req limit | Source |
|----------|---------------------|-----------|-----------|----------------------|--------|
| Grok (Foundry / NATE_CHAT_URL) | Env-driven | UNVERIFIED | UNVERIFIED | UNVERIFIED | **UNVERIFIED — console access required** |
| Azure OpenAI (chat + realtime) | `AZURE_OPENAI_ENDPOINT`, deployments in `sovereign_chat_client` / `inference_race` | UNVERIFIED | UNVERIFIED | UNVERIFIED | **UNVERIFIED — console access required** |
| Workers AI | Cloudflare | UNVERIFIED | UNVERIFIED | UNVERIFIED | **UNVERIFIED — console access required** |
| Sovereign (Ollama) | `SOVEREIGN_INFERENCE_URL`; inflight gate `SOVEREIGN_OVERFLOW_THRESHOLD` / `OLLAMA_NUM_PARALLEL` default 4 (`sovereign_chat_client.py:202-203`, `417-425`) | N/A (self-hosted) | N/A | **Observable in code:** `OVERFLOW_THRESHOLD` (default ties to `OLLAMA_NUM_PARALLEL`) | Code-derived concurrency ceiling for sovereign **only** |

**Optional production header capture:** `x-ratelimit-*` from HTTP responses — **not observed** in this audit (no log artifact).

### Token / time assumptions (for formula when quotas become known)

- **System prompt:** Capped at **32,000 characters** before provider (`8933-8936`) — not tokens; **rough token estimate UNVERIFIED** without tokenizer.
- **`max_completion_tokens`:** `_select_max_tokens` → **600** default or **1500** on depth phrases (`712-724`); streaming uses same cap (`8955`).
- **Wall-clock per turn:** **UNVERIFIED** in this audit (user cited prior load test / prod p50 elsewhere).

**Formula (given user’s template, only when RPM/TPM known):**

`concurrent_turns ≈ min(RPM/60 * avg_turn_seconds, TPM/(avg_input+avg_output_tokens)/60 * avg_turn_seconds)`

With **UNVERIFIED** inputs → **no numeric result**.

### Combined ceiling / binding constraint / 500 turns

- **Combined ceiling across race pool:** **UNVERIFIED** (quota numbers missing).
- **Binding constraint:** **UNVERIFIED**.
- **Headroom to 500 concurrent text-chat turns:** **UNVERIFIED** numerically.

**Code-only non-quota ceiling:** Sovereign path refuses slot when `_inflight_sovereign >= OVERFLOW_THRESHOLD` (`417-421`), default **4** parallel sovereign streams per bridge process (`202-203`), independent of TPM.

---

## §5 patch (replace “unobserved binding constraint” caveat)

**Replacement text (merge into existing §5):**  
Inference **TPM/RPM/concurrency ceilings** for Grok, Azure, Workers AI, and Cloudflare remain **UNVERIFIED in this repository snapshot** because provider consoles and production `x-ratelimit-*` logs were **not pulled** during this audit. **Sovereign (Ollama)** concurrent load is partially observable via `SOVEREIGN_OVERFLOW_THRESHOLD` / `OLLAMA_NUM_PARALLEL` in `sovereign_chat_client.py` (defaults tie to **4** parallel). The prior “unobserved binding constraint for external APIs” caveat is narrowed: **external quotas are still unobserved**; **self-hosted sovereign has an in-code inflight gate only**.

---

## §6 patch — single-page verdict table (numbers to merge)

Replace estimated inference rows with:

| Item | Value | Source |
|------|-------|--------|
| Bridge `db_pool.max_size` | **40** | `bridge_server.py:29972` |
| Bridge `chat_db_pool.max_size` | **8** | `bridge_server.py:29982` |
| Chat context parallel PG tasks (gather) | **4** | `bridge_server.py:8173-8180` |
| Sovereign parallel slot ceiling (default) | **4** | `sovereign_chat_client.py:202-203`, `417-421` |
| Grok/Azure/Workers TPM & RPM | **UNVERIFIED** | Phase 3b |
| Estimated 500-turn provider headroom | **UNVERIFIED** | Phase 3b |

---

*End of supplement.*

---
name: Cache-Dump Turn Architecture
overview: Implement the Deltoidal Icositetrahedron cache-dump turn management system, the predictive pre-fetch loop, the no-stutter rule, and close all identified cache/memory growth gaps discussed in conversation but not yet coded.
todos:
  - id: turn-dump-hook
    content: Wire turn dump to Hot Memory after memorize() in process_interaction. Use hot_memory.store() with session-scoped key and 2h TTL
    status: completed
  - id: replace-recall-by-session
    content: Replace recall_by_session PG query with Hot Memory Redis read of last 2 turns. Fallback to PG on cold start
    status: completed
  - id: wire-sdh-compressor
    content: Wire SDHContextCompressor.compress() into process_interaction, replacing the 15-block 24K f-string with a single ~800 token compressed context block
    status: completed
  - id: identity-cache
    content: Cache identity prompt portion in Hot Memory once per session (7200s TTL) instead of rebuilding per message
    status: completed
  - id: emergency-compression
    content: Implement >8 turns emergency compression using Workers AI/Grok (background, not user-facing) to summarize older turns
    status: completed
  - id: predictive-prefetch
    content: Build _predictive_prefetch() method using PMB + cycle detection predictions to pre-compute next turn context via Vectorize + SDH, store in Hot Memory with state hash
    status: completed
  - id: prefetch-hit-check
    content: "Add prefetch hit check at start of process_interaction: if state hash matches, skip all context assembly"
    status: completed
  - id: ttft-ceiling
    content: Add TTFT timeout per provider in sovereign_chat_client.py (Ollama 8s, Grok 3s, Workers 5s) with automatic reroute on timeout
    status: completed
  - id: inter-token-gap
    content: "Add inter-token gap monitor in streaming loop: buffer 3 tokens if gap exceeds 300ms to smooth perceived stutter"
    status: completed
  - id: typing-indicator
    content: Send typing_indicator WebSocket message during TTFT wait so client shows 'Little Nate is thinking...'
    status: completed
  - id: session-memory-cleanup
    content: "Add session_memory file cleanup to db_maintenance_agent: delete local files older than 7 days if R2-replicated"
    status: completed
  - id: active-tokens-timer
    content: Add 5-minute background timer for ACTIVE_TOKENS pruning in bridge_server.py
    status: completed
  - id: summon-crystallization
    content: Implement pre-expiry archival of summon responses to R2 + crystallization of high-confidence responses
    status: completed
  - id: r2-analytics-lifecycle
    content: "Configure R2 lifecycle rule for analytics JSONL: Infrequent Access at 90 days, delete at 365 days"
    status: completed
  - id: topology-rule
    content: Create deltoidal-icositetrahedron-turn-architecture.mdc rule with full kite-face topology, cache-dump rules, predictive model, no-stutter budget, and honest TPS numbers
    status: completed
isProject: false
---

# Cache-Dump Turn Architecture and Discussed-But-Unbuilt Systems

## The Problem

`process_interaction` in `bridge_server.py` (line 7980) rebuilds a ~24,000-character system prompt on every single message by:

- Calling `recall_by_session(session_limit=3, per_session=5)` which queries PostgreSQL for 500 rows, then truncates to 15 turn-pairs (~3,000-6,000 chars)
- Concatenating 15+ context blocks (observer, evocative, drift, reply therapy, workbook, etc.) synchronously on the asyncio event loop
- Trimming the result to 6,000 chars in `sovereign_chat_client.py` AFTER building the full 24K string

Meanwhile, the building blocks to avoid all of this already exist but are not wired:

- `SDHContextCompressor.compress()` in [sdh_context_compressor.py](backend/app/services/sdh_context_compressor.py) produces an 350-1,000 token compressed context block via 12-face dodecahedron topology -- but `process_interaction` never calls it
- `HotMemoryTier` in [memory/hot.py](backend/app/services/memory/hot.py) has `store_session_context()` and `get_session_context()` methods -- but zero callers exist
- `SDHPrecomputeCache` in [sdh_precompute_cache.py](backend/app/services/sdh_precompute_cache.py) supports face-path keyed caching with state hashes -- but `process_interaction` bypasses it
- PMB cyclical patterns, cycle detection, C_emo trajectory, shame tracking, and crisis perception all compute predictive signals -- but nothing runs between turns to pre-fetch the next turn's context

## Part 1: Cache-Dump Turn Management (The Core Build)

### 1A. Turn Dump Hook -- After Every AI Response

Wire into `process_interaction` after the existing `memorize()` call (which already writes to `conversation_history` PostgreSQL and Vectorize). Add a non-blocking dump of a compressed turn summary to Hot Memory Redis.

**File**: [bridge_server.py](backend/app/websocket/bridge_server.py) -- after line ~8708 where `memorize()` runs

```python
await hot_memory.store(f"hot:session:{uid}:turn:{turn_num}", {
    "user_text": user_text[:200],
    "ai_text": full_response[:200],
    "c_emo": nevedal_state.get("C_emo"),
    "mood": nevedal_state.get("mood_current"),
    "shame_index": nevedal_state.get("shame_profile", {}).get("shame_index", 0),
    "themes": nevedal_state.get("active_themes", [])[:5],
    "odpe_signal": nevedal_state.get("odpe_signal", "PROVISIONAL"),
}, ttl_seconds=7200)
```

The Hot Memory API in [memory/hot.py](backend/app/services/memory/hot.py) already has `store_session_context(session_id, context, ttl=7200)` and `get_session_context(session_id)` -- currently zero callers.

### 1B. Replace `recall_by_session` with Hot Memory Read

Replace the PostgreSQL query `recall_by_session(session_limit=3, per_session=5)` at line 8016 with a Redis read of the last 2 turn summaries from Hot Memory. This eliminates the per-message PG query that fetches 500 rows.

**Current** (line 8016):

```python
memory_context = self.mem.recall_by_session(profile, session_limit=3, per_session=5)
```

**New**:

```python
recent_turns = await hot_memory.retrieve(f"hot:session:{uid}:turn:*", limit=2)
memory_context = _format_recent_turns(recent_turns)  # 2 turns = ~300 tokens
```

When Hot Memory has no turns (first message in session), fall back to `recall_by_session` with `session_limit=1, per_session=2`.

### 1C. Wire SDH Compressor into `process_interaction`

Replace the 15+ context block concatenation (lines 8016-8374) with a single call to `SDHContextCompressor.compress()`.

**Current**: 15 separate context-building blocks (`memory_context`, `wisdom`, `family_context`, `sanctuary_context`, `relational_context`, `checkin_context`, `web_search_context`, `observer_context`, `evocative_context`, `drift_context`, `reply_context`, `workbook_guidance`) assembled into a 24K f-string.

**New**: Build a `raw_context` dict from these blocks and pass to `compress()`:

```python
raw_context = {
    "emotional": {"c_emo": cached_ns.get("C_emo"), ...},
    "relational": {"family": family_context, "coach": ...},
    "history": recent_turns,  # from Hot Memory, not PG
    "cognitive": {"wisdom": wisdom_text},
    "coherence": {"odpe": cached_ns.get("odpe_signal")},
    # ... map to the 12 FACE_DIMENSIONS
}
sdh_block = await sdh_compressor.compress(
    user_id=uid, helix_result=None, raw_context=raw_context,
    conversation_history=recent_turns, profile=profile,
    target_tokens=800, target_model="llama3.1:8b"
)
# sdh_block.compressed_context replaces the 24K f-string
```

The SDH compressor already has model-aware budgets (350-500 for 8B, 500-700 for 14B, 700-1000 for 32B) and conversation state hashing.

### 1D. Session Identity Cache

Cache the identity portion of the system prompt (lines 8375-8500, the constant ~4,000 chars) in Hot Memory once per session instead of rebuilding on every message.

```python
identity_key = f"hot:session:{uid}:identity"
cached_identity = await hot_memory.retrieve(identity_key)
if not cached_identity:
    cached_identity = _build_identity_prompt(profile)  # ~800 tokens compressed
    await hot_memory.store(identity_key, cached_identity, ttl_seconds=7200)
```

### 1E. Emergency Compression

When Hot Memory accumulates >8 turns for a session, compress turns 1 through N-2 into a summary using Azure/Workers AI (background, not user-facing). Store the summary as a single Hot Memory entry. Delete individual turn entries 1 through N-2.

This prevents Hot Memory from growing unbounded per session while preserving therapeutic continuity via summarization.

**Rule**: Emergency compression LLM call uses `force_overflow=True` (Workers AI or Grok, not Ollama) to avoid consuming sovereign inference slots.

---

## Part 2: Predictive Pre-Fetch (Faces 17-24 of the Deltoidal Icositetrahedron)

### 2A. Pre-Fetch Trigger

After the turn dump (Part 1A), launch an async background task (fire-and-forget, not on the critical path) that:

1. Reads PMB cyclical patterns from `nevedal_state` (already computed at line ~5686)
2. Reads cycle detection engine's current phase (already computed)
3. Predicts top-2 likely next topics from these signals
4. Runs `always_on_memory_recall` for predicted topics (Vectorize search -- zero cost)
5. Runs `SDHContextCompressor.compress()` with predicted context
6. Stores result at `hot:session:{uid}:prefetch` with conversation state hash and 10-min TTL

**File**: New method `_predictive_prefetch()` in [bridge_server.py](backend/app/websocket/bridge_server.py)

### 2B. Pre-Fetch Hit Check

At the start of `process_interaction`, before building any context:

```python
prefetch = await hot_memory.retrieve(f"hot:session:{uid}:prefetch")
if prefetch and prefetch.get("state_hash") == current_state_hash:
    sdh_block = prefetch["sdh_block"]  # Pre-computed, skip all context assembly
    prefetch_hit = True
else:
    # Standard path: build context, compress via SDH
    prefetch_hit = False
```

When prefetch hits, the entire context assembly (15+ blocks, PG query, SDH compression) is skipped. Context is ready in <1ms from Redis.

### 2C. Kite-Face Routing

When prefetch hits (context is small, pre-assembled), route to sovereign Ollama (context is tiny, fast prefill). When prefetch misses (larger context, built at request time), allow Azure/Workers AI overflow more aggressively since they handle larger contexts faster (~10,000+ tok/s prefill vs ~500 tok/s on ARM).

---

## Part 3: No-Stutter Rule (300ms Token Delivery Budget)

Currently no stutter prevention exists anywhere in the codebase (verified in conversation at transcript line 821).

### 3A. TTFT Ceiling

In `sovereign_chat_client.py`, add a TTFT timeout per provider:

- Ollama: 8 seconds max TTFT. If no first token arrives, cancel and reroute to Grok/Workers AI
- Grok: 3 seconds max TTFT
- Workers AI: 5 seconds max TTFT

### 3B. Inter-Token Gap Monitor

In the streaming loop at [bridge_server.py](backend/app/websocket/bridge_server.py) line ~8510, track the gap between consecutive tokens. If gap exceeds 300ms, buffer 3 tokens before resuming delivery to smooth perceived stutter.

### 3C. Typing Indicator

During the TTFT wait, send a `typing_indicator` message to the client so they see "Little Nate is thinking..." instead of silence. Currently nothing is sent between the user's message and the first response token.

### 3D. Cursor Rule

Create `deltoidal-icositetrahedron-turn-architecture.mdc` codifying the complete turn-load topology, the cache-dump rules, the predictive pre-fetch model, and the no-stutter budget. This rule was discussed in detail at transcript lines 812-814 and includes:

- Kite face vertex mapping (Prior Turn, Pattern State, Predicted Next, Current Turn)
- 24-face infrastructure distribution (4 Ollama, 4 Workers AI, 8 Grok/overflow, 8 predictive)
- Implementation rules 1-12 from the verified spec (transcript line 814)
- Honest TPS/TTFT numbers per provider

---

## Part 4: Cache Growth Gap Closures

### 4A. Session Memory File Cleanup

`SessionMemoryStore` in [session_memory_store.py](backend/app/services/session_memory_store.py) writes files to `{storage_root}/session_memories/{session_id}/` and to R2 -- but never deletes local files. At 10K sessions this becomes GBs.

Add a cleanup cycle to `db_maintenance_agent.py`:

- Scan `session_memories/` for directories older than 7 days
- Verify the session has been replicated to R2 (check `r2_replicated` flag in index.json)
- Delete local files for sessions confirmed in R2
- Log deletion count

### 4B. ACTIVE_TOKENS Background Sweep

Currently pruning only runs reactively when a new token is stored (line ~1867). Add a 5-minute background timer in [bridge_server.py](backend/app/websocket/bridge_server.py) that calls `_prune_expired_tokens()` regardless of login activity. This prevents unbounded in-memory growth during low-traffic periods.

### 4C. Summon Response Crystallization

When a summon response's KV/Redis TTL is about to expire, archive the response to R2 and optionally crystallize high-quality responses (confidence > 0.7) into `nate_intelligence_crystals`. Currently summon responses are lost entirely on TTL expiry.

Add a pre-expiry hook in the summon response cache layer that writes to R2 before the key expires.

### 4D. R2 Analytics JSONL Lifecycle

The `nate-analytics-edge` worker writes append-only JSONL to R2 with no TTL. Add an R2 lifecycle rule (via Cloudflare dashboard or API) to transition objects older than 90 days to Infrequent Access and delete after 365 days.

---

## Files Changed Summary


| File                                                             | Change                                                                                                                                               |
| ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `backend/app/websocket/bridge_server.py`                         | Wire SDH compressor into `process_interaction`, turn dump to Hot Memory, prefetch trigger, prefetch hit check, typing indicator, ACTIVE_TOKENS timer |
| `backend/app/services/sovereign_chat_client.py`                  | TTFT ceiling per provider, inter-token gap monitor                                                                                                   |
| `backend/app/services/session_memory_store.py`                   | Add `cleanup_old_sessions()` method                                                                                                                  |
| `backend/app/services/db_maintenance_agent.py`                   | Add session_memory cleanup to maintenance cycle                                                                                                      |
| `backend/app/services/summon_crystallizer.py`                    | New: pre-expiry archival + crystallization for summon responses                                                                                      |
| `.cursor/rules/deltoidal-icositetrahedron-turn-architecture.mdc` | New rule codifying the full topology, cache-dump rules, and no-stutter budget                                                                        |



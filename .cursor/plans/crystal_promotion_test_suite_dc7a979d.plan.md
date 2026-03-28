---
name: Crystal Promotion Test Suite
overview: Build a comprehensive pytest test file at backend/tests/test_crystal_promotion_paths.py that exercises all four crystal recall-and-promote paths, three storage backends, cross-path consistency, edge cases, and an ExaFLOPS integration proof — all self-contained with no external dependencies.
todos:
  - id: docstring
    content: "Write module docstring: list 4 paths with file:line, IEEE 754 explanation, PROMOTION_INCREMENT sensitivity analysis, expected runtime"
    status: completed
  - id: fixtures
    content: Build StatefulFakeConnection/Pool (in-memory crystal state, SQL regex parsing), tmp_local_store, crystal_seed factory
    status: completed
  - id: cap-fix
    content: "Fix PROMOTION_CAP inconsistency: change LEAST(..., 1.0) to LEAST(..., 0.95) in quantum_knowledge_field.py, nate_memory_crystallizer.py, littlenate_inference.py, bridge_server.py. Add test_cap_enforcement_all_paths that fails if any path allows confidence > 0.95."
    status: completed
  - id: part1
    content: "Part 1: 20 tests (4 paths x 5 confidence levels) exercising real functions with fake backends"
    status: completed
  - id: part2
    content: "Part 2: 3 storage backend tests (SQLite, PostgreSQL, Edge/KV) verifying 6-decimal precision, integer recall_count, timestamp freshness"
    status: completed
  - id: part3
    content: "Part 3: Cross-path consistency test (BLUE->GREEN->3 recalls->verify 0.69 in both stores)"
    status: completed
  - id: part4
    content: "Part 4: 11 edge case tests (concurrent race, ODPE boundary with threshold reconciliation, decay exemption, supersession x2, meta-crystal, LOCKED bypass x2, KV staleness xfail, NOISE skip, LOCKED double-increment)"
    status: completed
  - id: part5
    content: "Part 5: ExaFLOPS integration proof (10 seed crystals, 100 queries via real search_crystals, verify compounding RATE: free_responses[Q4] > free_responses[Q1])"
    status: completed
isProject: false
---

# Crystal Promotion Paths Test Suite

## The Four Recall Paths (Traced from Codebase)

### Path 1: FederatedSearch (Helix Orchestrator / therapy chat)

- **Entry**: `HelixOrchestrator.think()` -> `FederatedSearchCoordinator.search()` -> `_reinforce_recalls()`
- **Promotion SQL**: `quantum_knowledge_field.py` lines 395-434 (`_reinforce_recalls`) and lines 488-498 (`_search_server`)
- **Backend**: PostgreSQL
- **Cap**: `LEAST(..., 1.0)` -- caps at 1.0, NOT 0.95

### Path 2: Therapy Direct (always_on_memory_recall -> record_recall)

- **Entry**: `process_interaction()` -> `cortex` -> `always_on_memory_recall()` -> `record_recall()`
- **Promotion SQL**: `bridge_server.py` lines 4806-4824 (direct SQL) and `nate_memory_crystallizer.py` lines 2194-2229 (`record_recall`)
- **Backend**: PostgreSQL (GREEN) or SQLite (BLUE)
- **Cap**: `LEAST/MIN(..., 1.0)` -- caps at 1.0
- **ODPE behavior**: LOCKED signal doubles the increment (`increment = 2`, applied as multiplier to both `recall_count` and `confidence += 2 * 0.03 = 0.06`); NOISE skips update entirely (immediate return, no DB write). See Gap 3 (`test_noise_signal_skips_promotion`) and Gap 4 (`test_locked_signal_double_increment`).

### Path 3: CLI Crystal Recall

- **Entry**: `nate_cli_chat` handler -> `LocalCrystalStore.search_crystals()` (BLUE) or direct SQL (GREEN)
- **Promotion SQL**: `nate_memory_crystallizer.py` lines 153-183 (`search_crystals`) and `bridge_server.py` lines 28612-28637
- **Backend**: SQLite (BLUE) or PostgreSQL (GREEN)
- **Cap**: `min(conf + PROMO_INC, PROMOTION_CAP)` -- caps at 0.95 (both Python-side)

### Path 4: LittleNate Inference Enrichment

- **Entry**: `LittleNateInference.generate()` -> `_retrieve_crystals()`
- **Promotion SQL**: `littlenate_inference.py` lines 257-264
- **Backend**: PostgreSQL
- **Cap**: `LEAST(..., 1.0)` -- caps at 1.0

### Critical Bug: PROMOTION_CAP Inconsistency (Correction 1 -- FIX REQUIRED)

Paths 1, 2, 4 cap at 1.0 in SQL (`LEAST(..., 1.0)`). Path 3 caps at 0.95 (`PROMOTION_CAP`). All four paths MUST cap at `PROMOTION_CAP` (0.95) to match the canonical constant in `crystal_constants.py`.

**Fix**: Change `LEAST(..., 1.0)` to `LEAST(..., 0.95)` in:

- `quantum_knowledge_field.py` lines 400, 410, 420, 493 (`_reinforce_recalls` + `_search_server`)
- `nate_memory_crystallizer.py` lines 2200, 2218, 2270, 2320 (`record_recall` + `fetch_relevant`)
- `littlenate_inference.py` line 260 (`_retrieve_crystals`)
- `bridge_server.py` lines 4651, 4821 (`_recall_crystals_from_pg` + `always_on_memory_recall` direct SQL)

**Test**: `test_cap_enforcement_all_paths` seeds a crystal at 0.94, recalls it through each path, and asserts confidence is exactly 0.95 (not 0.97). This test deliberately FAILS against current code to prove the bug exists, then passes after the SQL fix.

---

## IEEE 754 Floating Point Precision

Three step values produce imprecise results:

- `0.66 + 0.03 = 0.6900000000000001`
- `0.81 + 0.03 = 0.8400000000000001`
- `0.93 + 0.03 = 0.9600000000000001`

All assertions must use `pytest.approx(expected, abs=1e-9)` for confidence comparisons. The docstring must explain why.

---

## Fixture Architecture

### `StatefulFakeConnection` (Correction 4 -- coupling warning)

A sophisticated fake asyncpg connection that maintains an in-memory dict of crystals, interprets UPDATE/SELECT SQL patterns via regex, and returns results consistent with actual PostgreSQL behavior. Key behaviors:

- `execute(UPDATE ...)` modifies the in-memory crystal state and returns `"UPDATE 1"`
- `fetch(SELECT ...)` reads from in-memory state
- `fetchrow(SELECT ...)` returns a single crystal dict
- Tracks all executed queries for assertion

**Mandatory class-level docstring** (Correction 4): The class must include a comment block explaining:

1. This class uses regex to parse SQL strings from production code
2. If production SQL is reformatted (whitespace, column order, alias changes), these patterns will break and tests will silently pass without exercising the real logic
3. This coupling exists because mocking at the asyncpg protocol level would require a full PostgreSQL wire protocol emulator, which is disproportionate for unit tests
4. When a test fails with "no SQL pattern matched," the first diagnostic step is to compare the regex against the current SQL in the source file cited in the test docstring

### `StatefulFakePool`

Wraps `StatefulFakeConnection` with `async with pool.acquire() as conn` context manager.

### `tmp_local_store`

Creates a `LocalCrystalStore(db_path=tmp_path / "test_crystals.db")` — real SQLite, temporary directory cleaned up by pytest.

### `crystal_seed` helper

A factory function that inserts a crystal with a given `confidence`, `domain`, `recall_count`, `content_hash` into either the fake PG pool or the SQLite store, returning the crystal dict.

### Patches required

- `app.services.vectorize_service.index_wisdom` / `is_vectorize_configured` -> mocked
- `app.services.vectorize_service.semantic_search_all` -> mocked (for graph rebuild)
- LLM/Grok inference -> mocked (for meta-crystal synthesis, LOCKED bypass verification)

---

## Test Structure

```
backend/tests/test_crystal_promotion_paths.py
|
|-- Module docstring (Part 6)
|
|-- Fixtures (conftest-style, local to file)
|   |-- StatefulFakeConnection / StatefulFakePool
|   |-- tmp_local_store (real SQLite via LocalCrystalStore)
|   |-- crystal_seed()
|
|-- class TestPath1_FederatedSearch  (5 confidence tests)
|-- class TestPath2_TherapyDirect   (5 confidence tests)
|-- class TestPath3_CLIRecall       (5 confidence tests)
|-- class TestPath4_InferenceEnrich (5 confidence tests)
|
|-- class TestStorageBackend_SQLite
|-- class TestStorageBackend_PostgreSQL
|-- class TestStorageBackend_EdgeKV
|
|-- class TestCrossPathConsistency
|   |-- test_blue_to_green_three_recalls
|
|-- class TestEdgeCases
|   |-- test_4a_concurrent_recall_race
|   |-- test_4b_odpe_signal_boundary_thresholds
|   |-- test_4b_odpe_bypass_vs_label_gap     (Gap 2)
|   |-- test_4c_decay_exempt_domains
|   |-- test_4d_supersession_crystallizer_contradiction
|   |-- test_4d_supersession_factory_merge
|   |-- test_4e_meta_crystal_promotion
|   |-- test_4f_locked_bypass_cli
|   |-- test_4f_locked_bypass_therapy
|   |-- test_noise_signal_skips_promotion    (Gap 3)
|   |-- test_locked_signal_double_increment  (Gap 4)
|   |-- test_kv_cache_staleness_window       (Gap 1, xfail)
|
|-- class TestExaFLOPSIntegration
|   |-- test_compounding_model
```

---

## Key Implementation Decisions

### Part 1: Testing actual functions, not just arithmetic

Each path test will instantiate the real class (e.g., `FederatedSearchCoordinator`, `NateMemoryCrystallizer`, `LocalCrystalStore`) with a fake DB pool or temp SQLite, inject a crystal, call the actual method, and verify the result in storage. This tests the real SQL/code, not a reimplementation.

### Part 2: Storage backend testing

- **SQLite**: Use `LocalCrystalStore` with `tmp_path`. Call `store_crystal()` then `search_crystals()` and verify confidence changes.
- **PostgreSQL**: Use `StatefulFakePool` that simulates SQL UPDATE behavior. The fake connection parses the SQL pattern to apply the correct arithmetic.
- **Edge/KV**: Mock the LOCKED bypass flow. Verify that when `confidence >= 0.85`, the crystal text is served directly and no LLM call is made (patched inference returns sentinel value that must NOT appear in output). Additionally, the `TestStorageBackend_EdgeKV` class includes the `test_kv_cache_staleness_window` xfail test (Gap 1) that documents the up-to-60-minute consistency window between PG and KV after a promotion event.

### Part 3: Cross-path consistency

Create crystal in `LocalCrystalStore`, call `sync_to_production()` (mocked to insert into fake PG pool), then exercise 3 different recall paths and verify the final confidence. The key assertion: `final_conf == pytest.approx(0.60 + 3 * 0.03, abs=1e-9)`.

### Part 4: Edge cases

- **4A**: Use `asyncio.gather` to fire two concurrent `record_recall` calls. With SQLite (which serializes), both will succeed. Document that PostgreSQL without `SELECT ... FOR UPDATE` may lose one update under real concurrency.
- **4B** (Gap 2 -- threshold reconciliation required):
The codebase has THREE different confidence-to-signal mappings that disagree:

  | Source                                          | LOCKED threshold           | PROMOTED threshold           |
  | ----------------------------------------------- | -------------------------- | ---------------------------- |
  | `crystal_constants.py`                          | 0.85 (`CONFIDENCE_LOCKED`) | 0.75 (`CONFIDENCE_PROMOTED`) |
  | CLI label (`bridge_server.py:28662`)            | 0.90                       | 0.75                         |
  | LOCKED bypass (`bridge_server.py:28652, 12781`) | 0.85                       | N/A                          |

  This creates a gap: a crystal at 0.87 triggers the LOCKED bypass (serves at $0, no LLM) but is LABELED as "PROMOTED" in the CLI system prompt context. The user sees "PROMOTED 87%" next to a response that was actually served via the LOCKED shortcut.
  **Tests**:
  - `test_4b_odpe_signal_boundary_thresholds`: Verify the canonical thresholds from `crystal_constants.py` (0.85 = LOCKED, 0.75 = PROMOTED, 0.60 = TENSION/PROVISIONAL). Test that a crystal at 0.74 is PROVISIONAL, at 0.75 is PROMOTED, at 0.84 is PROMOTED, at 0.85 is LOCKED.
  - `test_4b_odpe_bypass_vs_label_gap`: Seed a crystal at 0.87. Assert that the LOCKED bypass activates (confidence >= 0.85 check) BUT the CLI label logic (`_cc >= 0.90`) still classifies it as "PROMOTED". This test documents the labeling drift. Mark with a comment: `# BUG: CLI line 28662 uses 0.90 for LOCKED label, but bypass activates at 0.85 per crystal_constants.CONFIDENCE_LOCKED`.
- **4C**: Use the real `_decay_cycle()` method with fake pool. Verify `DECAY_EXEMPT_DOMAINS = {"coding", "defense", "machining", "crisis"}` and `CONFIDENCE_FLOOR_BY_DOMAIN` for each domain.
- **4D** (Correction 2 -- two supersession paths, not one):
There are TWO distinct supersession mechanisms in production. Both must be tested:
  1. **Crystallizer contradiction** (`nate_memory_crystallizer.py` line 1700): During `_cluster_and_synthesize_cycle()`, the contradiction detector finds an old crystal conflicting with a new one. If new confidence >= old confidence, the old crystal gets `superseded_by = -1` (sentinel, not the new crystal's ID) and `scope = 'archived'`. **recall_count is NOT inherited** -- this is a documented gap. Test: verify the old crystal is archived, the new crystal retains its own recall_count, and the `-1` sentinel is used.
  2. **Factory duplicate merge** (`crystal_factory.py` line 635, `merge_duplicates()`): Used during factory dedup cycles. Winner gets `recall_count = combined_recalls` (sum of both). Loser gets `superseded_by = keep_id` (real FK), `scope = 'archived'`. Test: verify winner has `combined_recalls`, loser references winner by ID, loser is archived not deleted.
  The test docstring must note that the crystallizer path does NOT inherit recall_count, which means knowledge value is lost during contradiction supersession. This is a gap for a future fix.
- **4E**: Insert a meta-crystal with `metadata = '{"is_meta_crystal": true}'`, `confidence = 0.70` (`META_CONFIDENCE`). Verify it promotes like a normal crystal.
- **4F** (Correction 3 -- two LOCKED bypass implementations, not one):
There are TWO distinct LOCKED bypass paths. Both must be tested:
  1. **CLI bypass** (`bridge_server.py` line 28920): When `_cli_odpe == "LOCKED"` and `_top_conf >= 0.85`, sets `_crystal_only_response = crystal_text`. Streams the crystal text directly as `nate_cli_chat_chunk`. No LLM inference call (`generate()`) is made. Test: mock the inference function, verify it is NOT called, verify response text equals the crystal text verbatim.
  2. **Therapy bypass** (`bridge_server.py` line 12775): When `fetch_relevant()` returns a crystal with `confidence >= 0.85`, sets `_therapy_crystal_bypass = True`. Sends the crystal text as an `ai_response` WebSocket message directly. `tract_pipeline.process()` is NOT called. Test: mock `tract_pipeline.process`, verify it is NOT called, verify the WebSocket message type is `ai_response` with `provider: "crystal_recall"` and `text` equals the crystal text.

### Gap 1: KV Cache Staleness Window (xfail)

The Cloudflare KV pre-warm cache (`SUMMON_CACHE` with `prewarm:` prefix, TTL 3600s) is populated by the `nate-cron-worker` hourly. When PostgreSQL promotes a crystal's confidence (e.g., 0.84 -> 0.87), the KV cache retains the stale 0.84 value until the next cron cycle. During this window, edge-served responses may use a crystal at PROMOTED level while the database knows it's LOCKED.

**Test**: `test_kv_cache_staleness_window`

- Seed a crystal at 0.84 in a mock KV store and in the fake PG pool
- Promote it through PostgreSQL to 0.87 via `record_recall`
- Read from the KV mock -- assert it still returns 0.84 (stale)
- Mark with `@pytest.mark.xfail(reason="KV cache has up to 60min staleness window — known architecture gap. Crystal promoted in PG is not propagated to KV until next cron pre-warm cycle.")`

This test exists to make the gap visible. It is not a code bug that can be fixed in this PR.

### Gap 3: NOISE Signal Skips Promotion

`record_recall()` in `nate_memory_crystallizer.py` line 2185 returns immediately when `odpe_signal == "NOISE"`. This is a quality gate: low-quality matches don't earn promotion credit, protecting crystal integrity.

**Test**: `test_noise_signal_skips_promotion`

- Seed a crystal at 0.70 confidence, recall_count = 5
- Call `record_recall(crystal_id, odpe_signal="NOISE")`
- Assert confidence is still exactly 0.70
- Assert recall_count is still exactly 5
- Assert `last_recalled_at` is unchanged (not updated)

### Gap 4: LOCKED Signal Double-Increment

`record_recall()` in `nate_memory_crystallizer.py` line 2188 sets `increment = 2` when `odpe_signal == "LOCKED"`. This is a multiplier applied to BOTH `recall_count` AND confidence:

```python
increment = 2 if odpe_signal == "LOCKED" else 1
# SQL: recall_count = recall_count + $2          ($2 = increment = 2)
# SQL: confidence = ... + $2 * PROMOTION_INCREMENT  (2 * 0.03 = 0.06)
```

So LOCKED recall means: `recall_count += 2` and `confidence += 0.06` (not two separate 0.03 bumps).

**Test**: `test_locked_signal_double_increment`

- Seed a crystal at 0.85 confidence, recall_count = 8
- Call `record_recall(crystal_id, odpe_signal="LOCKED")`
- Assert confidence is `pytest.approx(0.91, abs=1e-9)` (0.85 + 2 * 0.03)
- Assert recall_count is exactly 10 (8 + 2)
- Also test with a crystal at 0.93: confidence should be capped at 0.95 (after cap fix), not 0.99

### Part 5: ExaFLOPS integration (Correction 5 -- assert compounding RATE)

Simulate 100 queries against 10 seed crystals using real `LocalCrystalStore.search_crystals()` for retrieval (Gap 5 -- must exercise actual search, not random assignment). The 10 seed crystals cover 3 domains with distinct keywords. The 100 queries are a deterministic list where ~60% contain keywords that overlap with seed crystal text and ~40% contain unrelated terms. The match is determined by `search_crystals()` keyword logic (SQLite LIKE), not random selection. This means the test exercises the real retrieval-and-promote pipeline end-to-end on SQLite.

Track metrics in 4 quartiles (Q1: queries 0-24, Q2: 25-49, Q3: 50-74, Q4: 75-99):

- `free_response_count` per quartile (LOCKED bypass activations)
- `avg_confidence` per quartile
- `promotion_events` per quartile

**The ExaFLOPS proof is not just "did counts increase?" but "did the rate accelerate?"**:

```python
# The compounding assertion: later quartiles produce MORE free responses
# because earlier recalls promoted crystals into LOCKED territory
assert free_by_quartile[3] > free_by_quartile[0], (
    "ExaFLOPS model broken: Q4 free responses must exceed Q1. "
    f"Q1={free_by_quartile[0]}, Q4={free_by_quartile[3]}"
)
assert avg_conf_by_quartile[3] > avg_conf_by_quartile[0], (
    "Confidence must compound over time"
)
```

Additionally assert:

- Total crystal count > 10 (new crystals from TENSION resolutions)
- At least one crystal reached PROMOTED (0.75+)
- If any crystal hit LOCKED (0.85+), `free_by_quartile[3] > 0`

---

## SQL Cap Fix Scope (Correction 1)

The test file includes `test_cap_enforcement_all_paths` which asserts no path allows confidence above 0.95. Before the SQL fix, this test will fail for Paths 1, 2, 4. The fix changes `1.0` to `0.95` in these SQL strings:

- `quantum_knowledge_field.py` `_reinforce_recalls()`: 3 SQL UPDATE statements use `LEAST(..., 1.0)` -- change to `LEAST(..., 0.95)`
- `quantum_knowledge_field.py` `_search_server()`: 1 SQL UPDATE uses `LEAST(..., 1.0)` -- change to `LEAST(..., 0.95)`
- `nate_memory_crystallizer.py` `record_recall()`: 2 SQL UPDATEs (BLUE SQLite uses `MIN(..., 1.0)`, GREEN PG uses `LEAST(..., 1.0)`) -- change both to `0.95`
- `nate_memory_crystallizer.py` `fetch_relevant()`: 2 SQL UPDATEs (BLUE + GREEN) -- change to `0.95`
- `littlenate_inference.py` `_retrieve_crystals()`: 1 SQL UPDATE -- change to `0.95`
- `bridge_server.py` `_recall_crystals_from_pg()`: 1 SQL UPDATE -- change to `0.95`
- `bridge_server.py` `always_on_memory_recall()` direct SQL: 1 SQL UPDATE -- change to `0.95`

Total: ~11 SQL statement changes across 4 files. Each must use the imported `PROMOTION_CAP` constant (or the f-string equivalent `{PROMOTION_CAP}`) rather than hardcoding `0.95`.

---

## Files to Read During Implementation

- [backend/app/services/crystal_constants.py](backend/app/services/crystal_constants.py) — all constants
- [backend/app/services/quantum_knowledge_field.py](backend/app/services/quantum_knowledge_field.py) — Path 1 (`_reinforce_recalls`, `_search_server`)
- [backend/app/services/nate_memory_crystallizer.py](backend/app/services/nate_memory_crystallizer.py) — Path 2/3 (`record_recall`, `search_crystals`, `fetch_relevant`, `_decay_cycle`, `LocalCrystalStore`, `DECAY_EXEMPT_DOMAINS`, `CONFIDENCE_FLOOR_BY_DOMAIN`)
- [backend/app/services/littlenate_inference.py](backend/app/services/littlenate_inference.py) — Path 4 (`_retrieve_crystals`)
- [backend/app/websocket/bridge_server.py](backend/app/websocket/bridge_server.py) — Path 2/3 entry points, CLI handler, LOCKED bypass
- [backend/app/services/crystal_graph.py](backend/app/services/crystal_graph.py) — meta-crystal synthesis, `META_CONFIDENCE = 0.70`
- [backend/crystal_factory.py](backend/crystal_factory.py) — `merge_duplicates()` supersession
- [backend/tests/conftest.py](backend/tests/conftest.py) — existing fixture patterns


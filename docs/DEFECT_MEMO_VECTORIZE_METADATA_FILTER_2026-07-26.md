# Defect Memo — Vectorize Metadata Filtering Non-Functional (Semantic Retrieval Silently Empty)

**Date of memo**: 2026-07-26
**Status**: **FIXED (code + Cloudflare config).** Metadata indexes created on all 8 Vectorize indexes. Application post-filter fallback restores retrieval immediately. Boot-time capped re-upsert makes native filtering work for high-confidence crystals. Recorded as its own workstream (not folded into Phase 5c/5d).
**Severity**: Degraded capability, not an outage. No data loss, no exposure, no user-visible error.
**Prepared by**: Engineering (Cursor agent session). Verified against production Cloudflare account and `nate_backend` on GREEN (68.183.168.75).

---

## 1. What was broken

Little Nate has two long-term memory retrieval paths:

1. **PostgreSQL crystal recall** — `recall_crystals_for_context()`. **Unaffected.**
2. **Cloudflare Vectorize semantic search** — `semantic_search()` / `semantic_search_all()`. Applied a `user_id` metadata filter on every call, but **no metadata indexes existed** on any of the eight indexes. Native filters returned empty; call sites treated that as "nothing relevant."

---

## 2. Two previously unverified concerns — now verified

### 2a. Are metadata indexes retroactive?

**No.** Cloudflare docs and production canary agree:

| Probe (2026-07-26, after creating indexes) | Result |
|---|---|
| Unfiltered query on pre-existing corpus | 5 matches |
| Filtered `user_id=nate_crystal` on same corpus | 0–1 matches (bulk still unindexed) |
| Upsert new vector **after** index create, then filter | Filterable |

Docs: *"metadata indexes need to be created … before vectors can be inserted to support metadata filtering."* Existing vectors require **re-upsert** to become filterable.

### 2b. Are current-format crystal writes landing in `nate-wisdom`?

**Yes.** Sample of top-50 unfiltered hits (2026-07-26):

| Shape | Count | Evidence |
|---|---|---|
| Legacy `wisdom_<int>` ids, `user_id=''`, `insight_type=crystal` | 35 | Pre-`_make_vector_id` era |
| SHA-256 ids, `user_id=nate_crystal`, `insight_type=crystal_clinical` | 15 | Current crystallizer path |

Neither shape carried `wisdom_id` or `content_hash` in metadata before this fix (both are written now).

---

## 3. Direction chosen (not "indexes only")

Creating eight×six metadata indexes alone would **not** restore retrieval for the existing corpus (non-retroactive). Better direction, implemented:

| Layer | Action |
|---|---|
| Cloudflare | Create `user_id`, `family_id`, `group_id`, `company_id`, `wisdom_id`, `content_hash` (string) on all 8 indexes — **done** |
| Immediate retrieval | `VECTORIZE_POST_FILTER_FALLBACK=true` (default): if native filter returns empty → unfiltered query + Python equality post-filter (privacy preserved) |
| Write path | `index_wisdom()` always writes `wisdom_id` + `content_hash`; never stores empty `user_id` (defaults to `nate_crystal`) |
| Crystal graph | Resolve neighbors via `content_hash` / `wisdom_id`; scope queries per node owner |
| Corpus heal | Boot task `reindex_wisdom_crystals(limit=CRYSTAL_GRAPH_MAX_EDGE_NODES)` re-upserts top-N crystals so native filters work for the graph edge set |
| Observability | Startup prints metadata-index readiness + reindex counts |

Full historical reindex of ~200k crystals is **not** required for exit; post-filter covers the long tail. Expand the reindex limit later if native-filter hit rate needs to rise.

---

## 4. Cloudflare state (verified)

```
nate-memory-search -> 6 [company_id, content_hash, family_id, group_id, user_id, wisdom_id]
nate-vault-search  -> 6 [...]
nate-wisdom        -> 6 [...]
nate-me2me         -> 6 [...]
nate-sessions      -> 6 [...]
nate-annotations   -> 6 [...]
nate-predictive    -> 6 [...]
nate-code-search   -> 6 [...]
```

---

## 5. Code touchpoints

| File | Change |
|---|---|
| `backend/app/services/vectorize_service.py` | `ensure_metadata_indexes`, post-filter fallback, `index_wisdom` metadata, `reindex_wisdom_crystals` |
| `backend/app/services/crystal_graph.py` | Neighbor resolution + per-node scope |
| `backend/app/main.py` | Boot bootstrap task (metadata indexes + capped reindex); CrystalGraph first rebuild delayed to 300s |
| `.env.template` | `VECTORIZE_POST_FILTER_FALLBACK`, reindex note on `CRYSTAL_GRAPH_MAX_EDGE_NODES` |

---

## 6. Exit criteria

1. All 8 indexes list the 6 metadata properties — **met**
2. `semantic_search(..., user_id=nate_crystal)` returns non-empty via native filter **or** post-filter fallback — verify after deploy
3. `crystal_edges` gains `semantic_neighbor` rows after next CrystalGraph rebuild — verify after deploy + ~5–10 min
4. Canary: new upsert after index create is natively filterable — **met** (2026-07-26)

---

## 7. Why this stayed hidden

Empty results looked like "nothing relevant"; PostgreSQL recall masked the Vectorize path; the missing piece lived in Cloudflare account state with no auditor. The bootstrap print + post-filter log line close that gap.

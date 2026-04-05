---
name: Verify-Before-Voice Pipeline
overview: Evaluate Gemini's 6-component "Chain-of-Verification" architecture against the existing search pipeline, implement what genuinely adds value, and adapt the rest to the real-time voice constraint where latency budgets prohibit multi-second verification loops.
todos:
  - id: authority-scoring
    content: Add authority scoring to SecureSearchProxy.sanitize_result() — TLD-based + known-domain scoring, sort results by authority in format_for_nate()
    status: completed
  - id: parallel-burst
    content: Modify _web_search() to run primary + contextual variant in parallel via asyncio.gather, merge/dedup results
    status: completed
  - id: verbal-citation
    content: Enhance _inject_web_context() with authority metadata and spoken domain name mapping so Grok can cite sources naturally
    status: completed
  - id: audit-trail
    content: Add skyeye_activity insert for voice search grounding events in _background_search_and_inject()
    status: completed
isProject: false
---

# Verify-Before-Voice Pipeline: Gemini Proposals vs. Existing Architecture

## Honest Assessment: What Gemini Gets Right and Wrong

Gemini's architecture assumes a **text chat** where 2-5 seconds of verification latency is invisible. Little Nate's voice pipeline operates on a **live phone call** where any pause beyond ~1.5 seconds feels like dead air. The "draft, verify, rewrite" loop that Gemini calls the "secret sauce" would add 3-8 seconds of latency per turn — unacceptable for real-time audio.

However, 3 of Gemini's 6 components fill genuine gaps in the existing pipeline. The plan below implements the valuable parts while adapting them to the real-time constraint.

---

## Existing Infrastructure (Do NOT Rebuild)

These already exist and work. Gemini's proposals must layer on top, not replace:

- `**SecureSearchProxy`** ([search_proxy.py](backend/app/services/search_proxy.py)) — DuckDuckGo/Bing search, domain blocklist, injection detection, SSRF prevention, rate limiting with burst allowance
- `**NateResponseValidator**` ([nate_response_validator.py](backend/app/services/nate_response_validator.py)) — 9-layer hallucination detection, factual grounding (Layer 8), crystal filtering
- `**_extract_web_query()**` ([twilio_grok_xtts_pipeline.py](backend/app/services/twilio_grok_xtts_pipeline.py)) — 5-stage Precision Strike query reconstruction
- `**PredictiveEntityGraph**` — Entity extraction, preloading, crystallization
- `**FederatedSearchCoordinator**` ([quantum_knowledge_field.py](backend/app/services/quantum_knowledge_field.py)) — Parallel crystal/RAG search (server DB + Vectorize + edge)
- **26 Auditors + Trust Enforcer** — Full trust scorecard infrastructure
- `**SearchAuditLogger`** — JSONL-based audit trail for search events

---

## What to Implement (3 Components)

### 1. Source Authority Scoring (Gemini's "AuthorityFilter")

**Gap it fills:** `SecureSearchProxy` blocks dangerous domains but does NOT rank trustworthy ones. All search results currently have equal weight — a `.gov` clinical guideline and a random blog post are treated identically.

**Adaptation:** Add authority scoring to `ContentSanitizer.sanitize_result()` in [search_proxy.py](backend/app/services/search_proxy.py). Each result gets an `authority_score` (0.0-1.0) based on TLD and known domains.

**Important correction to Gemini:** The blocklist Gemini proposes is too aggressive. Blocking YouTube blocks podcast content (like Dr. Livernois's School Talks). Blocking Reddit blocks legitimate clinical discussions. The approach should be **scoring, not blocking** — rank `.gov`/`.edu` higher, but don't exclude `.com` domains that may have the exact content the user is asking about.

```python
AUTHORITY_TIERS = {
    ".gov": 0.95,
    ".edu": 0.90,
    "ncbi.nlm.nih.gov": 1.0,
    "apa.org": 0.95,
    "samhsa.gov": 1.0,
    "apple.com": 0.80,  # podcast directory
    ".org": 0.70,
    ".com": 0.50,  # default for commercial
}
```

- Add `authority_score` field to each result in `sanitize_result()`
- Sort results by authority score in `format_for_nate()` so Grok sees the highest-authority source first
- Include authority metadata in the injected context so Grok can cite appropriately

**File:** [backend/app/services/search_proxy.py](backend/app/services/search_proxy.py) — modify `sanitize_result()` and `format_for_nate()`

### 2. Parallel Search Burst (Gemini's "BurstSearchManager")

**Gap it fills:** `_web_search()` currently searches sequentially — primary, then phonetic fallback, then crystal fuzzy. For queries with entities, running 2-3 search variants simultaneously would cut latency from ~3-5 seconds to ~1-2 seconds.

**Adaptation:** Modify `_web_search()` in [twilio_grok_xtts_pipeline.py](backend/app/services/twilio_grok_xtts_pipeline.py) to use `asyncio.gather` for the primary search + one contextual variant simultaneously, NOT as a separate `BurstSearchManager` class.

```python
# In _web_search(), after building clean_query:
contextual_query = f"{clean_query} {current_year}"
entity_query = f"{' '.join(entity_hints[:2])} {clean_query}" if entity_hints else None

tasks = [_do_search(clean_query)]
if entity_query and entity_query != clean_query:
    tasks.append(_do_search(entity_query))
primary_results, *extra = await asyncio.gather(*tasks)
```

- Use existing `_do_search()` wrapper (inherits timeout, error handling)
- Merge results with deduplication by URL
- Only fall back to phonetic/fuzzy if parallel batch returned nothing
- Keep the 8-second total timeout per search

**File:** [backend/app/services/twilio_grok_xtts_pipeline.py](backend/app/services/twilio_grok_xtts_pipeline.py) — modify `_web_search()`

### 3. Verbal Citation Framing (Gemini's "SourceCitationSynthesizer")

**Gap it fills:** `_inject_web_context()` tells Grok "summarize the results" but doesn't tell Grok WHICH source to cite or how to frame the citation. Adding source authority metadata and citation framing instructions to the injection context helps Grok say "According to the NIH..." instead of just paraphrasing.

**Adaptation:** Enhance `_inject_web_context()` to include authority scores and a spoken-name mapping in the injected context message.

```python
# In _inject_web_context, add source authority info:
for result in safe_results:
    source_label = SPOKEN_DOMAIN_NAMES.get(domain, domain)
    context_line = f"[{source_label}, authority: {score}] {snippet}"
```

Add to the system prompt instruction: "When citing, use the source name in brackets. Prefer high-authority sources. Say 'According to [source name]...' for .gov/.edu sources."

**File:** [backend/app/services/twilio_grok_xtts_pipeline.py](backend/app/services/twilio_grok_xtts_pipeline.py) — modify `_inject_web_context()`. Also modify `format_for_nate()` in [search_proxy.py](backend/app/services/search_proxy.py) to include authority metadata.

---

## What NOT to Implement (and Why)

### Chain-of-Verification (CoVe) Loop — REJECT

Gemini's "draft, verify, rewrite" loop requires:

1. Grok generates a hidden draft (~2-3s)
2. Python extracts claims from the draft (~0.5s)
3. 3 parallel verification searches (~1-2s)
4. Compare and rewrite (~0.5-1s)

**Total: 4-7 seconds of dead air on a phone call.** This is the opposite of the existing architecture which searches BEFORE Grok responds and injects results as context. The existing approach is better for voice:

```
User speaks → search triggers → thinking cue plays → search runs (~1-2s) →
results injected → Grok responds WITH the facts already in context
```

The CoVe pattern is valuable for text chat but destructive for voice.

### ConflictResolver — REJECT (Over-Engineered)

The existing pipeline returns 3 results max. Grok is already excellent at synthesizing multiple sources. Adding a Python arbitration layer that compares results, computes cosine similarity against crystals, and produces a "winner" adds latency and complexity for a marginal accuracy improvement. If authority scoring is implemented (Component 1), the highest-authority source is already ranked first, which is sufficient for Grok to prioritize.

### Full Auditor Dashboard — DEFER

The auditor infrastructure (26 auditors, Trust Enforcer, SkyEye) already exists. Adding a search-specific "Hallucination Heatmap" or "Trust Score Live Feed" is a UI task that can be done later. The audit logging improvement below provides the data foundation.

---

## Supporting Enhancement: Unified Search Audit Trail

Extend `SearchAuditLogger` to also write to `skyeye_activity` (not just JSONL) so search events are visible in the existing SkyEye dashboard and auditor reports.

```python
# In _background_search_and_inject, after successful injection:
if db_pool:
    await db_pool.execute(
        "INSERT INTO skyeye_activity (type, content, platform) VALUES ($1, $2, $3)",
        "voice_search_grounding",
        json.dumps({"query": final_q, "results_count": len(safe_results),
                     "top_authority": top_score, "user": username}),
        "voice_call",
    )
```

**File:** [backend/app/services/twilio_grok_xtts_pipeline.py](backend/app/services/twilio_grok_xtts_pipeline.py) — add to `_background_search_and_inject()`

---

## Implementation Constraints

- `**twilio_grok_xtts_pipeline.py` is a PROTECTED FILE** — max 50 lines changed per commit, additive only, all changes behind `# SOVEREIGN-VOICE` comment
- `**search_proxy.py`** is not protected but changes must preserve the existing `SecureSearchProxy` API
- No new service files needed — all changes are enhancements to existing functions
- Must pass syntax check before deploy
- Must not increase search latency beyond 8-second total budget


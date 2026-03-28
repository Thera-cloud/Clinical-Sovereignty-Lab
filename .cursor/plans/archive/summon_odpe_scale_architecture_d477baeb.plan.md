---
name: Summon ODPE Scale Architecture
overview: "Wire summon through ODPE inference router, add Redis response cache, enable multi-worker uvicorn, clone VPS for horizontal scaling, then deploy Phase 11 edge layer (Cloudflare Workers + KV + D1) to handle public summon traffic at global edge with 85%+ cache hit rate and dual-brain resonance comparison. Combined effect: 500x+ cost reduction vs commercial APIs, capacity from ~50K/hr to unlimited, zero app user impact."
todos:
  - id: summon-odpe
    content: "Wire NateSummonService through inference router: add app_state, rewrite _generate_response, update main.py construction"
    status: completed
  - id: redis-cache
    content: "Add Redis response cache: create async client on app.state, add cache get/set methods to summon service, wire into _generate_response"
    status: completed
  - id: multi-worker
    content: "Enable multi-worker uvicorn: update Dockerfile CMD to --workers 4, increase docker-compose resource limits"
    status: completed
  - id: clone-docs
    content: Create VPS clone infrastructure documentation and docker-compose.clone.yml with Cloudflare LB setup procedure
    status: completed
  - id: edge-worker
    content: Create nate-summon-worker Cloudflare Worker with KV cache, Workers AI inference, device fingerprint rate limiting, and D1 logging
    status: completed
  - id: dual-brain
    content: "Implement dual-brain resonance: edge Worker queries sovereign brain on PROVISIONAL signals, compares via embedding similarity, selects best response"
    status: completed
  - id: internal-endpoint
    content: Add /api/summon/internal endpoint for secure edge-to-origin communication with EDGE_INTERNAL_TOKEN auth
    status: completed
  - id: deploy-verify
    content: Deploy all phases sequentially, verify ODPE routing, cache hit rates, edge Worker health, and dual-brain resonance on PROVISIONAL queries
    status: completed
isProject: false
---

# Summon ODPE Scale Architecture + Phase 11 Edge

## Phase 1: Route Summon Through ODPE Inference Router

The core fix. Currently `NateSummonService._generate_response()` calls Azure GPT-4o directly via `httpx`. It needs to use `NateInferenceRouter.generate()` instead, which routes 70% to Workers AI (free), 25% to Grok ($0.00025), and skips 5% (NOISE).

### 1a. Add `app_state` to NateSummonService

In [backend/app/services/nate_summon_service.py](backend/app/services/nate_summon_service.py):

- Add `app_state=None` parameter to `__init`__
- Store as `self._app_state`

### 1b. Rewrite `_generate_response` to use inference router

Replace the direct Azure `httpx` call (lines 224-263) with:

```python
async def _generate_response(self, message, max_tokens, context=None):
    router = getattr(self._app_state, "inference_router", None) if self._app_state else None
    
    context_text = ""
    if context:
        if context.get("page_url"):
            context_text += f"\n[User is viewing: {context['page_url']}]"
        if context.get("selected_text"):
            context_text += f"\n[Selected text: {context['selected_text'][:500]}]"
    
    full_prompt = f"{context_text}\n\n{message}" if context_text else message
    
    if router:
        result = await router.generate(
            prompt=full_prompt,
            system=SUMMON_SYSTEM_PROMPT,
            tier="utility",
            max_tokens=max_tokens,
            domain="general",
        )
        text = (result.get("text") or "").strip()
        if text:
            return text
    
    # Fallback to direct Azure call (existing code)
    ...
```

This uses `tier="utility"` which routes: Workers AI -> Grok -> Azure. The cheapest chain.

### 1c. Update main.py construction

In [backend/app/main.py](backend/app/main.py), change the NateSummonService instantiation (~line 2711) to pass `app_state`:

```python
_nate_summon_service = NateSummonService(
    db_pool=db_pool, privacy_shield=_privacy_shield, app_state=app.state
)
```

---

## Phase 2: Redis Response Cache

Identical questions (especially from ChatGPT MCP where multiple users ask "what is stress?") return cached responses. Target: 60% cache hit rate.

### 2a. Create shared async Redis client on app.state

In [backend/app/main.py](backend/app/main.py), during lifespan startup:

```python
import redis.asyncio as aioredis
_cache_redis = aioredis.from_url(redis_url, decode_responses=True)
app.state.cache_redis = _cache_redis
```

### 2b. Add cache check to NateSummonService

In [backend/app/services/nate_summon_service.py](backend/app/services/nate_summon_service.py):

- Cache key: `summon:cache:{sha256(message.lower().strip())}`
- TTL: 3600 seconds (1 hour)
- Only cache `access_level="full"` responses
- Check cache before inference router, store after successful AI call

### 2c. Cache-aware analytics

In `process_summon()`, set `sources_used=["nate_ai_cached"]` for cached responses so analytics distinguish cached vs fresh.

---

## Phase 3: Multi-Worker Uvicorn (4 workers)

### 3a. Update Dockerfile CMD

In [backend/Dockerfile](backend/Dockerfile), add `--workers 4`.

### 3b. Multi-worker safety

- `_rate_limits` in `summon_api.py` becomes per-worker (acceptable: 40 req/min instead of 10)
- `_sessions` in `mcp_server.py` is per-worker (MCP sessions may break across workers; horizontal scaling via clone handles this better)

### 3c. Docker Compose resource limits

In [docker-compose.prod.yml](docker-compose.prod.yml), increase backend limits to `cpus: "3.0"`, `memory: 4G`.

---

## Phase 4: VPS Clone Infrastructure (174.138.43.30)

Clone VPS is already provisioned on DigitalOcean.


| Property   | Value                           |
| ---------- | ------------------------------- |
| Public IP  | 174.138.43.30                   |
| Private IP | 10.116.0.2                      |
| Specs      | 4 vCPU / 8 GB RAM / 160 GB disk |
| Region     | NYC1 (same as primary)          |
| Cost       | ~$25.93/mo                      |


### 4a. Clone as backend-only node

- Install Docker, clone repo, copy `.env`
- Point `DATABASE_URL` and `REDIS_URL` at primary VPS via private networking
- Run `docker-compose.clone.yml` (backend only, no postgres/redis/bridge)

### 4b. Primary VPS firewall

Allow clone (10.116.0.2) access to PostgreSQL (5432) and Redis (6379) over DigitalOcean private networking.

### 4c. Cloudflare Load Balancing

Add both origins for `api.sovereignsanctuary.net`, health check on `GET /health`, round-robin.

---

## Phase 5: Phase 11 Edge Layer — Summon at Global Edge

This is the transformation phase. Move the public-facing summon traffic entirely onto Cloudflare's edge network while keeping the VPS sovereign brain for therapy, coaching, and admin workloads.

### Architecture After Phase 5

```
Public summon traffic (ChatGPT, browser ext, Alexa, web)
    |
    v
Cloudflare Worker "nate-summon-worker" (300+ PoPs)
    |
    +-- Workers KV cache check (85% hit rate, global)
    |       Hit → return cached response (<10ms)
    |
    +-- Cache miss → Workers AI (Llama 3.1 8B, free, at edge)
    |       |
    |       +-- ODPE PROVISIONAL signal?
    |       |       Yes → also query sovereign brain via origin
    |       |       Compare responses (dual-brain resonance)
    |       |       Crystallize agreement/divergence
    |       |
    |       +-- Store response in KV cache (1hr TTL)
    |       +-- Return response
    |
App therapy/coach/admin traffic (unchanged)
    |
    v
VPS-1 (primary) + VPS-2 (clone) via Cloudflare LB
    |
    +-- Bridge (WebSocket, Sentinel, Nevedal engine)
    +-- Inference Router (Grok, Sovereign, Azure fallback)
    +-- PostgreSQL, Redis, 31 auditors, trust system
```

### 5a. Create `nate-summon-worker` Cloudflare Worker

New file: `cloudflare/workers/nate-summon-worker/worker.js`

This Worker handles `POST api.sovereignsanctuary.net/api/summon` at the edge:

- Parse request, extract message + context + device fingerprint
- **KV cache check**: `SUMMON_CACHE` namespace, key = `sha256(message.lower().strip())`
  - Hit: return cached JSON immediately (sub-10ms, any PoP globally)
  - Miss: continue to inference
- **"3 Queries in a Bottle" enforcement**: `SUMMON_RATE` namespace tracks anonymous device fingerprints
  - If `remaining <= 0`, return throttle response
- **Workers AI inference**: Call `@cf/meta/llama-3.1-8b-instruct` via AI binding (free with Workers Paid)
  - System prompt: same `SUMMON_SYSTEM_PROMPT` as the Python service
  - Temperature: 0.6, max_tokens: 1000
- **Store result** in `SUMMON_CACHE` with 3600s TTL
- **Log to D1**: Insert summon interaction for analytics

New file: `cloudflare/workers/nate-summon-worker/wrangler.toml`

```toml
name = "nate-summon-worker"
main = "worker.js"
compatibility_date = "2026-03-01"

routes = [
  { pattern = "api.sovereignsanctuary.net/api/summon", zone_name = "sovereignsanctuary.net" }
]

[ai]
binding = "AI"

[[kv_namespaces]]
binding = "SUMMON_CACHE"
id = "<create via wrangler kv:namespace create SUMMON_CACHE>"

[[kv_namespaces]]
binding = "SUMMON_RATE"
id = "<create via wrangler kv:namespace create SUMMON_RATE>"

[[d1_databases]]
binding = "D1_HOT"
database_name = "nate-hot"
database_id = "8dcd53ad-a6fb-49f4-8ca9-5a5843489cd0"
```

### 5b. Dual-Brain Resonance (PROVISIONAL queries)

When the edge Worker gets a query that scores ambiguously (no strong cache signal, complex phrasing), it fires a parallel request to the origin VPS:

```javascript
// Edge Worker — dual inference for ambiguous queries
const edgeResponse = await env.AI.run("@cf/meta/llama-3.1-8b-instruct", {
    messages: [{ role: "system", content: SYSTEM_PROMPT }, { role: "user", content: message }],
    max_tokens: 1000
});

// Parallel: ask sovereign brain via origin
const sovereignResponse = await fetch("https://api.sovereignsanctuary.net/api/summon/internal", {
    method: "POST",
    headers: { "Authorization": "Bearer " + env.INTERNAL_TOKEN, "Content-Type": "application/json" },
    body: JSON.stringify({ message, source: "edge_resonance" })
});

// Compare and select
const edgeText = edgeResponse.response;
const sovereignData = await sovereignResponse.json();
const sovereignText = sovereignData.response;

// Simple agreement check: cosine similarity of sentence embeddings
const edgeEmbed = await env.AI.run("@cf/baai/bge-small-en-v1.5", { text: [edgeText] });
const sovEmbed = await env.AI.run("@cf/baai/bge-small-en-v1.5", { text: [sovereignText] });
const similarity = cosineSimilarity(edgeEmbed.data[0], sovEmbed.data[0]);

if (similarity > 0.85) {
    // LOCKED — high agreement, use faster edge response, cache it
    await env.SUMMON_CACHE.put(cacheKey, edgeText, { expirationTtl: 7200 }); // longer TTL for validated
    return edgeText;
} else {
    // TENSION — use sovereign response (clinical depth), flag divergence
    await env.SUMMON_CACHE.put(cacheKey, sovereignText, { expirationTtl: 3600 });
    return sovereignText;
}
```

This is the physical manifestation of the ODPE dodecahedron/icositetragon resonance comparison.

### 5c. New internal endpoint for sovereign brain queries

In [backend/app/routers/summon_api.py](backend/app/routers/summon_api.py), add:

```python
@router.post("/internal")
async def summon_internal(request: Request, body: dict):
    """Edge Worker calls this for dual-brain resonance comparison."""
    internal_token = os.getenv("EDGE_INTERNAL_TOKEN", "")
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {internal_token}":
        raise HTTPException(403, "Not authorized for internal endpoint")
    
    message = body.get("message", "")
    if not message:
        raise HTTPException(400, "message required")
    
    # Use sovereign inference (Grok/Qwen, NOT Workers AI — that's what the edge already tried)
    response = await summon_service._generate_response(message, max_tokens=1000)
    return {"response": response, "source": "sovereign_brain"}
```

### 5d. KV namespace creation and deployment

```bash
cd cloudflare/workers/nate-summon-worker
wrangler kv:namespace create SUMMON_CACHE
wrangler kv:namespace create SUMMON_RATE
# Update wrangler.toml with returned IDs
wrangler deploy
```

### 5e. Add `EDGE_INTERNAL_TOKEN` to `.env`

New env var for the secure edge-to-origin communication channel. Generate via `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.

---

## Phase 5 Cost Impact


| Metric                        | Fixed+Clone (Phase 1-4)    | + Phase 11 Edge (Phase 5)                               |
| ----------------------------- | -------------------------- | ------------------------------------------------------- |
| Cost per summon request       | $0.000028                  | $0.000011                                               |
| Cache hit rate                | 60% (Redis, single region) | 85% (Workers KV, 300+ PoPs)                             |
| Response latency (cache hit)  | ~50ms (origin round-trip)  | <10ms (edge PoP)                                        |
| Response latency (cache miss) | ~2-5s (origin AI)          | ~1-3s (Workers AI at edge)                              |
| Infrastructure cost           | $68/mo (2 VPS)             | $5/mo (Workers Paid) + $68/mo (VPS for sovereign brain) |
| Capacity ceiling              | ~10M req/hr (2 nodes)      | Unlimited (300+ PoPs)                                   |
| App user isolation            | Full (ODPE routing)        | Full (edge never touches VPS for cached)                |
| Dual-brain resonance          | No                         | Yes (edge vs sovereign comparison on PROVISIONAL)       |


## Files Modified / Created


| File                                                  | Change                                                                   |
| ----------------------------------------------------- | ------------------------------------------------------------------------ |
| `backend/app/services/nate_summon_service.py`         | Add `app_state`, rewrite `_generate_response`, add cache methods         |
| `backend/app/main.py`                                 | Pass `app_state` to NateSummonService, create `cache_redis` on app.state |
| `backend/Dockerfile`                                  | Add `--workers 4` to uvicorn CMD                                         |
| `docker-compose.prod.yml`                             | Increase CPU/memory limits for backend                                   |
| `backend/app/routers/summon_api.py`                   | Add `/internal` endpoint for edge-to-origin resonance                    |
| `infrastructure/clone-vps.md`                         | New: VPS clone procedure documentation                                   |
| `docker-compose.clone.yml`                            | New: Slimmed compose for clone VPS                                       |
| `cloudflare/workers/nate-summon-worker/worker.js`     | New: Edge Worker for summon at global edge                               |
| `cloudflare/workers/nate-summon-worker/wrangler.toml` | New: Worker config with KV, D1, AI bindings                              |
| `.env.template`                                       | Add `EDGE_INTERNAL_TOKEN`                                                |


## Deployment Order

1. **Phase 1 + 2** (summon ODPE routing + Redis cache) — code changes only, zero cost, deploy to primary VPS
2. Restart backend, verify summon uses Workers AI/Grok via logs, test cache hit/miss
3. **Phase 3** (multi-worker) — Dockerfile change, requires image rebuild
4. **Phase 4** (clone VPS) — only when traffic demands it, $26/mo
5. **Phase 5** (edge Worker) — `wrangler deploy`, creates KV namespaces, routes summon to edge. VPS becomes sovereign brain only for PROVISIONAL queries. Summon traffic never hits VPS for cached responses.


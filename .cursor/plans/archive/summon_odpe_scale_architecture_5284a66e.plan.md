---
name: Summon ODPE Scale Architecture
overview: "Wire the summon service through the ODPE inference router (eliminating direct Azure calls), add a Redis response cache for repeated questions, enable multi-worker uvicorn, and document the VPS clone procedure. Combined effect: 12-250x cost reduction and capacity from ~50K/hr to 10M/hr with zero app user impact."
todos:
  - id: summon-odpe
    content: "Wire NateSummonService through inference router: add app_state, rewrite _generate_response, update main.py construction"
    status: completed
  - id: redis-cache
    content: "Add Redis response cache: create async client on app.state, add cache get/set methods to summon service, wire into _generate_response"
    status: completed
  - id: multi-worker
    content: "Enable multi-worker uvicorn: update Dockerfile CMD, increase docker-compose resource limits, audit MCP session safety"
    status: completed
  - id: clone-docs
    content: Create VPS clone infrastructure documentation with Cloudflare LB setup procedure
    status: completed
  - id: deploy-verify
    content: Deploy all changes, verify ODPE routing via logs, test cache hit rate, confirm app chat isolation
    status: completed
isProject: false
---

# Summon ODPE Scale Architecture

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

The inference router is set on `app.state` before summon service is used (both are set during lifespan), so the router will be available when `_generate_response` runs.

---

## Phase 2: Redis Response Cache

Identical questions (especially from ChatGPT MCP where multiple users ask "what is stress?") should return cached responses. Target: 60% cache hit rate.

### 2a. Create shared async Redis client on app.state

In [backend/app/main.py](backend/app/main.py), during lifespan startup (near existing Redis setup code):

```python
import redis.asyncio as aioredis
_cache_redis = aioredis.from_url(redis_url, decode_responses=True)
app.state.cache_redis = _cache_redis
```

The package `redis[hiredis]~=5.0.1` is already in requirements.txt and supports async via `redis.asyncio`.

### 2b. Add cache check to NateSummonService

In [backend/app/services/nate_summon_service.py](backend/app/services/nate_summon_service.py):

- Before calling the inference router, hash the message and check Redis
- Cache key: `summon:cache:{sha256(message.lower().strip())}`
- TTL: 3600 seconds (1 hour)
- Only cache `access_level="full"` responses (not limited/blocked)
- Store as JSON: `{"response": "...", "provider": "cached"}`

```python
async def _get_cached_response(self, message: str) -> Optional[str]:
    cache = getattr(self._app_state, "cache_redis", None) if self._app_state else None
    if not cache:
        return None
    key = f"summon:cache:{hashlib.sha256(message.lower().strip().encode()).hexdigest()}"
    try:
        cached = await cache.get(key)
        return cached if cached else None
    except Exception:
        return None

async def _set_cached_response(self, message: str, response: str):
    cache = getattr(self._app_state, "cache_redis", None) if self._app_state else None
    if not cache:
        return
    key = f"summon:cache:{hashlib.sha256(message.lower().strip().encode()).hexdigest()}"
    try:
        await cache.setex(key, 3600, response)
    except Exception:
        pass
```

Wire into `_generate_response`: check cache first, store after successful AI call.

### 2c. Cache-aware response in process_summon

In `process_summon()`, after the cache check, set `sources_used=["nate_ai_cached"]` so analytics can distinguish cached vs fresh responses.

---

## Phase 3: Multi-Worker Uvicorn (8 workers)

Currently the backend runs a single uvicorn worker (no `--workers` flag in [backend/Dockerfile](backend/Dockerfile)).

### 3a. Update Dockerfile CMD

Change line 43 of the Dockerfile from:

```
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

To:

```
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "8"]
```

### 3b. Multi-worker safety audit

Two in-memory structures break with multiple workers:

- `**_rate_limits` dict in `summon_api.py**` — per-IP burst limiting becomes per-worker. At 8 workers, effective limit is 8x the intended cap. Acceptable for now (80 req/min instead of 10). For strict enforcement, move to Redis INCR with TTL.
- `**_sessions` dict in `mcp_server.py**` — MCP SSE sessions are in-memory. A session created in worker 1 won't be found in worker 2. Fix: either use Redis for session queues, or configure uvicorn with `--workers 1` initially and scale horizontally via VPS cloning instead.

**Recommendation:** Keep `--workers 4` (not 8) to balance throughput vs MCP session affinity. The VPS clone handles the other 4x.

### 3c. Docker Compose resource limits

In [docker-compose.prod.yml](docker-compose.prod.yml), increase the backend CPU/memory limits:

```yaml
deploy:
  resources:
    limits:
      cpus: "3.0"    # was 1.5
      memory: 4G      # was 2G
```

---

## Phase 4: VPS Clone Infrastructure (174.138.43.30)

Clone VPS is already provisioned and running on DigitalOcean.

### Clone VPS Details


| Property   | Value                           |
| ---------- | ------------------------------- |
| Droplet    | ubuntu-s-4vcpu-8gb-nyc1-01      |
| Public IP  | 174.138.43.30                   |
| Private IP | 10.116.0.2                      |
| Specs      | 4 vCPU / 8 GB RAM / 160 GB disk |
| Region     | NYC1 (same as primary)          |
| OS         | Ubuntu 24.04 LTS x64            |
| Cost       | ~$25.93/mo (already running)    |


### 4a. Set up clone as backend-only node

On the clone VPS (174.138.43.30):

- Install Docker + Docker Compose
- Clone repo: `git clone git@github.com:Thera-cloud/Clinical-Sovereignty-Lab.git /opt/clinical-sovereignty-lab`
- Copy `.env` from primary (68.183.168.75)
- Modify `.env` on clone: point `DATABASE_URL` and `REDIS_URL` at primary VPS private IP
  - `DATABASE_URL=postgresql://nate_app:PASSWORD@10.116.0.2_PRIMARY:5432/little_nate` (use primary's private IP if on same VPC, or public IP with firewall rule)
  - `REDIS_URL=redis://:PASSWORD@PRIMARY_PRIVATE_IP:6379`
- Create a slimmed `docker-compose.clone.yml` that runs backend only (no postgres, redis, bridge, admin containers)
- `docker compose -f docker-compose.clone.yml up -d`

### 4b. Primary VPS firewall: allow clone access to PostgreSQL and Redis

On the primary VPS (68.183.168.75):

- Allow PostgreSQL port 5432 from clone's private IP (10.116.0.2)
- Allow Redis port 6379 from clone's private IP
- Both should be over DigitalOcean private networking (free, low-latency, same VPC in NYC1)

### 4c. Cloudflare Load Balancing

Add both VPS IPs as origins for `api.sovereignsanctuary.net`:

- Origin 1: 68.183.168.75 (primary)
- Origin 2: 174.138.43.30 (clone)
- Health check: `GET /health` on port 443
- Load balancing policy: Round Robin or Least Connections

```
Cloudflare LB (api.sovereignsanctuary.net)
    |
    +--- VPS-1 (68.183.168.75): backend + bridge + postgres + redis
    |
    +--- VPS-2 (174.138.43.30): backend only (connects to VPS-1 postgres + redis via private network)
```

### 4d. Shared state requirements

The clone connects to the primary's PostgreSQL and Redis over DigitalOcean private networking. No data replication needed. Both nodes read/write the same database and response cache. The WebSocket bridge stays on the primary only -- summon/REST API traffic is what gets load-balanced.

---

## Files Modified


| File                                          | Change                                                                                   |
| --------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `backend/app/services/nate_summon_service.py` | Add `app_state`, rewrite `_generate_response` to use inference router, add cache methods |
| `backend/app/main.py`                         | Pass `app_state` to NateSummonService, create `cache_redis` on app.state                 |
| `backend/Dockerfile`                          | Add `--workers 4` to uvicorn CMD                                                         |
| `docker-compose.prod.yml`                     | Increase CPU/memory limits for backend                                                   |
| `infrastructure/clone-vps.md`                 | New file: VPS clone procedure documentation                                              |
| `docker-compose.clone.yml`                    | New file: Slimmed compose for clone VPS (backend only, no postgres/redis/bridge)         |


## Deployment Order

1. Deploy Phase 1 + 2 (summon routing + cache) -- code changes only, zero cost
2. Restart backend, verify summon uses Workers AI/Grok via logs
3. Test cache: send same question twice, second should return in under 50ms
4. Deploy Phase 3 (multi-worker) -- Dockerfile change, requires image rebuild
5. Phase 4 (clone) -- only when traffic demands it, $20/mo


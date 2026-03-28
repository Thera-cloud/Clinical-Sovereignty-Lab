---
name: Redis Session Hardening
overview: Harden the Redis token/session infrastructure, fix Safari login redirect, and clean up Hive Defense navigation duplication. The plan addresses all 14 Redis improvements, the Safari compatibility issue, and the UI duplication.
todos:
  - id: redis-health
    content: Add startup health check and periodic ping loop for token Redis client in bridge_server.py
    status: completed
  - id: token-ttl
    content: Add 10% TTL buffer to Redis SETEX and change eviction policy to volatile-lru in redis.conf
    status: completed
  - id: config-centralize
    content: Centralize Redis config dict, add startup validation, add environment key namespace
    status: completed
  - id: token-lifecycle
    content: Add atomic revocation (memory + Redis DEL), document lifecycle, add emergency revoke function
    status: completed
  - id: logging
    content: Add structured logging for token create/recover/expire/revoke events
    status: completed
  - id: safari-fix
    content: Fix Safari redirect with setTimeout delay, add sessionStorage try/catch in index.html and command.html
    status: completed
  - id: hardware-id-fix
    content: Stabilize hardware_id generation in index.html to stop creating a new device identity on every login
    status: completed
  - id: hive-nav
    content: Remove redundant Hive Defense nav link from skyeye.html
    status: completed
  - id: deploy
    content: Deploy all changes, restart bridge, verify admin login in both Chrome and Safari
    status: completed
isProject: false
---

# Redis Session Hardening, Safari Fix, and UI Cleanup

## Current State

- **Redis**: 7-alpine, `maxmemory 256mb`, eviction `allkeys-lru`, AOF+RDB persistence
- **Token TTL**: 24 hours in both `ACTIVE_TOKENS` (memory) and Redis `SETEX`
- **Token Redis client**: sync `redis.Redis` sharing the Swarm Relay's client (fixed earlier this session)
- **Key pattern**: `nate:auth:{token}` — no environment namespace
- **Health checks**: Docker-level ping exists; no app-level periodic health check on the token Redis path
- **Safari issue**: `window.location.href` redirect fires immediately after `sessionStorage.setItem()` in the `onmessage` handler, with no try/catch or delay — Safari may not persist storage before the redirect
- **Hive Defense**: both `command.html` and `skyeye.html` have nav links to the same `hive_defense.html` — not a data/Docker overlap, just redundant navigation

---

## Phase 1: Redis Reliability (Items 1-3)

### 1a. Health check Redis on startup

- In [bridge_server.py](backend/app/websocket/bridge_server.py) `main()`, after sharing the Swarm Relay client, verify connectivity with `_token_redis_sync.ping()` and log success/failure
- If unhealthy, log a loud warning but still start (graceful degradation)

### 1b. Periodic health ping with auto-reconnect

- Add a background task `_token_redis_health_loop()` that pings the token Redis client every 60 seconds (same pattern as `SwarmRelayServer._health_ping()` in [swarm_relay.py](backend/app/services/swarm_relay.py) line 212)
- On ping failure, set `_token_redis_sync = None` and attempt reconnection using the same sync Redis initialization code
- Log each failure and recovery

### 1c. Persist critical data in PostgreSQL, use Redis as cache only

- Tokens are already ephemeral (24h TTL) — Redis is the correct store for them
- No change needed: the PostgreSQL `users` table holds persistent identity; Redis holds short-lived auth tokens
- Document this architecture decision in a code comment at the top of the token section in `bridge_server.py`

---

## Phase 2: Token Lifecycle (Items 4-6)

### 2a. Align Redis TTL with token lifetime + buffer

- Currently `TOKEN_TTL_HOURS = 24` and Redis SETEX uses `TOKEN_TTL_HOURS * 3600 = 86400s`
- Add a 10% buffer: `SETEX` TTL = `int(TOKEN_TTL_HOURS * 3600 * 1.1)` = 95040s
- This prevents tokens from expiring in Redis slightly before the in-memory check

### 2b. Change eviction policy to `volatile-lru`

- Current: `allkeys-lru` — can evict ANY key including active tokens under memory pressure
- Change to: `volatile-lru` in [redis.conf](redis/redis.conf) — only evict keys with a TTL set, and only when memory limit is hit
- Since all token keys have TTL (`SETEX`), they are eligible for eviction under pressure, but non-expiring keys (if any) are protected

### 2c. Set TTL on all session/token keys

- All token keys already use `SETEX` with TTL — confirmed
- Add logging in `_store_token_redis` and `_get_token_profile_async` for token create/read/miss events (not just errors)

---

## Phase 3: Configuration and Key Patterns (Items 7-8)

### 3a. Centralize config

- Create a `_REDIS_CONFIG` dict at module level in `bridge_server.py`:
  ```python
  _REDIS_CONFIG = {
      "host": os.environ.get("REDIS_HOST", "redis"),
      "port": int(os.environ.get("REDIS_PORT", "6379")),
      "password": os.environ.get("REDIS_PASSWORD"),
      "key_prefix": os.environ.get("REDIS_KEY_PREFIX", "nate"),
  }
  ```
- Validate all required config values on startup (fail loud if `REDIS_PASSWORD` is missing)

### 3b. Consistent key namespacing

- Current pattern: `nate:auth:{token}` — good
- Add environment namespace: `{prefix}:{env}:auth:{token}` where `env` comes from `ENVIRONMENT` env var (default `prod`)
- Update all `nate:auth:` references in `_store_token_redis` and `_get_token_profile_async`

---

## Phase 4: Secret Rotation and Cluster Readiness (Items 9-10)

### 4a. Secret rotation support

- Currently tokens are keyed by their own hash — rotating `JWT_SECRET` doesn't invalidate existing Redis tokens
- No immediate change needed: tokens in Redis are self-contained (profile JSON), not JWT-signed
- Add a `_revoke_all_tokens()` function that uses `SCAN` + `DEL` on the token prefix for emergency revocation

### 4b. Cluster-aware client (deferred)

- Current setup is single-node Redis — no clustering
- When scaling to cluster: switch to `redis.RedisCluster` with SSL and password
- Mark this as a TODO in the code for future scaling

---

## Phase 5: Token Lifecycle Documentation and Consistency (Items 11-12)

### 5a. Document token lifecycle

- Add a docstring block at the top of the token section in `bridge_server.py` covering:
  - Where tokens are stored (memory + Redis)
  - TTL (24h + 10% buffer in Redis)
  - How revocation works (memory: delete from `ACTIVE_TOKENS`; Redis: `DEL` key)
  - How recovery works (Redis fallback on cache miss)

### 5b. Atomic revocation

- When a user logs out or token is revoked, delete from BOTH `ACTIVE_TOKENS` and Redis in the same operation
- Currently logout only clears memory — add Redis `DEL` in the logout handler

---

## Phase 6: Logging (Items 13-14)

### 6a. Add logging around session lifecycle

- Token created: log `[TOKEN] Stored {hw_id} (memory + Redis)`
- Token recovered from Redis: already logs `[TOKEN] Recovered from Redis`
- Token expired: log `[TOKEN] Expired for {hw_id}`
- Token revoked: log `[TOKEN] Revoked for {hw_id}`
- Redis unavailable: already logs, but add retry count

---

## Phase 7: Safari Login Fix and Hardware ID Stabilization

### 7a. Why Safari blocks the redirect (root cause)

The admin login flow is:

1. User clicks **Proceed** (user gesture)
2. JS sends `verify_admin_passphrase` over WebSocket (still user gesture context)
3. Bridge processes and responds with `passphrase_verified` (async — **no longer a user gesture**)
4. `onmessage` handler runs `window.location.href = 'command.html'`

Safari's ITP (Intelligent Tracking Prevention) treats navigations in asynchronous callbacks as **non-user-initiated** and may silently block or ignore them. Chrome is more permissive. This is NOT a popup — the passphrase challenge is a `<div>` overlay — but Safari treats the async redirect itself as suspicious.

### 7b. Fix: delayed redirect

- In [dashboard/index.html](dashboard/index.html), the passphrase redirect at line 563:
  ```javascript
  // Current (breaks Safari):
  window.location.href = 'command.html';

  // Fixed:
  setTimeout(() => { window.location.replace('command.html'); }, 150);
  ```
- The 150ms `setTimeout` gives Safari time to flush `sessionStorage` writes before navigating
- `window.location.replace()` prevents "back" from returning to the login page

### 7c. Wrap sessionStorage in try/catch

- Safari Private Browsing throws on `sessionStorage.setItem()` — wrap all writes in try/catch in both `index.html` and `command.html`
- If parse fails in `command.html` `init()`, clear storage and redirect to login

### 7d. Stabilize hardware_id generation

**Problem**: Line 686 of `index.html` generates:

```javascript
hardware_id: `WEB_${navigator.userAgent.slice(0, 20)}_${Date.now()}`
```

Because `Date.now()` changes every millisecond, **every login creates a brand-new device identity**. This causes:

- Sentinel sees every login as an "unknown device" -> triggers anomaly scoring
- Old tokens accumulate in Redis with orphaned hardware_ids
- Token recovery on reconnect fails because the hardware_id never matches

**Fix**: Generate a stable per-browser fingerprint and persist it in `localStorage`:

```javascript
function getStableHardwareId() {
    let hwid = localStorage.getItem('_nate_hwid');
    if (!hwid) {
        hwid = 'WEB_' + navigator.userAgent.slice(0, 20).replace(/\s/g, '_') + '_' + crypto.randomUUID().slice(0, 8);
        try { localStorage.setItem('_nate_hwid', hwid); } catch(e) {}
    }
    return hwid;
}
```

- Uses `localStorage` (survives page reloads and session clears), not `sessionStorage`
- Generated once per browser, reused on every login
- Sentinel will correctly recognize the device on subsequent logins
- Token recovery will match the stored hardware_id

---

## Phase 8: Hive Defense Navigation Cleanup

### 8a. Remove redundant Hive Defense link from SkyEye

- In [dashboard/skyeye.html](dashboard/skyeye.html) line 399, remove the Hive Defense nav item
- Hive Defense stays as a top-level tab in `command.html` (its proper home)
- No data/Docker overlap — both are links to the same `hive_defense.html`

---

## File Change Summary


- `bridge_server.py` — Health ping loop, config centralization, key namespacing, logging, revocation, TTL buffer
- `redis/redis.conf` — Eviction policy `allkeys-lru` to `volatile-lru`
- `dashboard/index.html` — Safari redirect delay, sessionStorage try/catch, stable hardware_id generation
- `dashboard/command.html` — JSON.parse try/catch, sessionStorage error handling
- `dashboard/skyeye.html` — Remove Hive Defense nav link



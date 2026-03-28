---
name: VPS Clone Redundancy
overview: Deploy a clone of the DigitalOcean VPS from a snapshot as a warm standby origin, with the clone connecting to the primary's PostgreSQL and Redis over the VPC private network. Reconfigure Cloudflare Load Balancer for active-active REST API routing with WebSocket pinned to the primary via a Custom Rule.
todos:
  - id: expose-db-redis
    content: Expose PostgreSQL and Redis on primary VPS VPC interface (port mappings + ufw + redis bind check)
    status: pending
  - id: snapshot-deploy
    content: Create DO snapshot and deploy clone droplet in SFO2 same VPC
    status: pending
  - id: configure-clone
    content: Create docker-compose.clone.yml, modified nginx config, update .env on clone
    status: pending
  - id: reconfigure-lb
    content: Consolidate LB pools, add clone to sovereign-core, create ws-primary pool + Custom Rule, enable Dynamic Steering
    status: pending
  - id: verify-failover
    content: Verify health checks, traffic distribution, WebSocket pinning, and failover behavior
    status: pending
  - id: update-docs
    content: Update LOAD_BALANCER_CONFIG.md and cloudflare-load-balancer.mdc rule with Phase 2 config
    status: pending
isProject: false
---

# Phase 2 — VPS Clone + Redundancy

> **Execution Order:** 1 of 4 — EXECUTE FIRST
> **Priority:** TIER 1 (infrastructure)
> **Status note:** Clone VPS (159.65.108.25) already exists per cloudflare-load-balancer.mdc. LB configured. This plan may be partially complete — verify each step against live state before executing.
> **DO Container Registry:** Use `registry.digitalocean.com/sovereign-container-repo` for image consistency between primary and clone.

## Architecture

```mermaid
flowchart TD
    subgraph CF [Cloudflare Edge]
        LB[Load Balancer\napi.sovereignsanctuary.net]
        CR[Custom Rule\npath /ws* -> ws-primary pool]
    end

    subgraph DO_VPC [DigitalOcean VPC 10.120.0.0/20 — SFO2]
        subgraph Primary [Primary VPS — 68.183.168.75\n10.120.0.2]
            nginx1[nginx :443]
            backend1[FastAPI :8000]
            bridge1[Bridge :8765]
            pg[PostgreSQL :5432]
            redis[Redis :6379]
        end

        subgraph Clone [Clone VPS — NEW_IP\n10.120.0.x]
            nginx2[nginx :443]
            backend2[FastAPI :8000]
        end
    end

    LB -->|"REST API\n(Dynamic Steering)"| nginx1
    LB -->|"REST API\n(Dynamic Steering)"| nginx2
    CR -->|"WebSocket /ws*\n(primary only)"| nginx1

    backend2 -->|"DATABASE_URL\n10.120.0.2:5432"| pg
    backend2 -->|"REDIS_URL\n10.120.0.2:6379"| redis
    backend1 --> pg
    backend1 --> redis
    bridge1 --> pg
    bridge1 --> redis
```



**Key constraints:**

- Clone runs FastAPI + nginx only (no bridge, no PostgreSQL, no Redis)
- Bridge stays on the primary only (in-memory WebSocket state cannot be shared)
- PostgreSQL and Redis stay on the primary only (shared via VPC private IP)
- WebSocket traffic (`/ws`*) is pinned to the primary via Cloudflare Custom Rule
- REST API traffic is load-balanced across both origins

---

## Step 1: Expose PostgreSQL + Redis on VPC Interface (Primary)

Currently, PostgreSQL and Redis have **no ports exposed** — they run on an `internal: true` Docker network. The clone needs to reach them via `10.120.0.2`.

### 1a. Add port mappings in `docker-compose.prod.yml` on the primary

Bind PostgreSQL and Redis to the VPC private interface only:

```yaml
postgres:
  ports:
    - "10.120.0.2:5432:5432"

redis:
  ports:
    - "10.120.0.2:6379:6379"
```

This ensures the ports are only reachable from the VPC network, not from the public internet.

### 1b. Verify Redis `bind` directive

Check `redis/redis.conf` — if it contains `bind 127.0.0.1`, Redis will reject connections through the port mapping even though Docker is forwarding. Inside the container, the connection arrives from the Docker bridge gateway, not 127.0.0.1. Either:

- Remove the `bind` directive (accept all interfaces inside the container)
- Or set `bind 0.0.0.0` (equivalent for Docker containers)

The `requirepass` directive provides security, so binding to all interfaces inside the container is safe.

### 1c. UFW rules for VPC-only access

```bash
ufw allow from 10.120.0.0/20 to any port 5432 proto tcp comment "PostgreSQL from VPC"
ufw allow from 10.120.0.0/20 to any port 6379 proto tcp comment "Redis from VPC"
```

These ensure only VPC peers (the clone) can reach these ports. The DigitalOcean Cloud Firewall typically passes VPC traffic, but verify this or add rules there too.

### 1d. Verify connectivity

After restarting docker-compose, test from the primary itself:

```bash
psql -h 10.120.0.2 -U nate_app -d little_nate -c "SELECT 1"
redis-cli -h 10.120.0.2 -a $REDIS_PASSWORD ping
```

---

## Step 2: Create Snapshot and Deploy Clone

### 2a. Power off cleanly (optional but recommended for data consistency)

```bash
ssh root@68.183.168.75 "docker compose -f docker-compose.prod.yml stop"
```

### 2b. Create snapshot in DigitalOcean Dashboard

Dashboard -> Droplets -> nate-vps -> Snapshots -> Take Snapshot.
Name: `nate-vps-clone-2026-03-14`
Wait for completion (5-10 minutes).

### 2c. Deploy clone from snapshot

Dashboard -> Images -> Snapshots -> Create Droplet from snapshot.

- **Region**: SFO2 (same as primary)
- **Size**: 2 vCPU / 4 GB RAM / $24/mo (same as primary for safe headroom; can downsize to 1 vCPU/2 GB ($12/mo) later if the backend runs comfortably)
- **VPC**: Select the same VPC as the primary (`default-sfo2`)
- **Name**: `nate-vps-clone`

### 2d. Restart primary

```bash
ssh root@68.183.168.75 "docker compose -f docker-compose.prod.yml up -d"
```

---

## Step 3: Configure Clone

SSH into the clone at its new IP.

### 3a. Create `docker-compose.clone.yml`

A minimal compose file that runs only backend + nginx:

```yaml
services:
  backend:
    # Same as primary, but:
    # - No depends_on (postgres/redis are remote)
    # - DATABASE_URL and REDIS_URL point to primary VPC IP
    environment:
      - DATABASE_URL=postgresql://nate_app:${NATE_APP_DB_PASSWORD}@10.120.0.2:5432/${POSTGRES_DB:-little_nate}
      - REDIS_URL=redis://:${REDIS_PASSWORD}@10.120.0.2:6379
      - REDIS_HOST=10.120.0.2
      # ... rest of env vars same as primary

  nginx:
    # Same as primary, but depends_on only backend
    # Uses a modified nginx.conf (see 3b)

# No postgres, redis, bridge, or admin services
```

### 3b. Modified nginx config for clone

The clone's nginx config is identical to the primary's EXCEPT:

- `/ws` location returns 502 (no bridge running)
- No proxy_pass to admin console (not running)

This ensures:

- REST API traffic (`/api/*`, `/health`) works normally through the clone
- WebSocket attempts to the clone fail fast, letting Cloudflare route them to the primary via the Custom Rule

### 3c. Stop and disable unused services

```bash
docker stop nate_postgres nate_redis nate_bridge nate_admin 2>/dev/null
docker rm nate_postgres nate_redis nate_bridge nate_admin 2>/dev/null
docker volume rm postgres_data redis_data 2>/dev/null
```

### 3d. Update `.env` on clone

Change connection strings to point to primary's VPC IP:

```
DATABASE_URL=postgresql://nate_app:PASSWORD@10.120.0.2:5432/little_nate
POSTGRES_HOST=10.120.0.2
REDIS_URL=redis://:PASSWORD@10.120.0.2:6379
REDIS_HOST=10.120.0.2
```

### 3e. Start clone with the clone compose file

```bash
docker compose -f docker-compose.clone.yml up -d
```

### 3f. Verify clone health

```bash
curl -s http://localhost:8000/health        # FastAPI via Docker
curl -sk https://CLONE_IP/health            # nginx -> FastAPI
docker logs nate_backend --since 1m 2>&1 | grep "STARTUP COMPLETE"
```

---

## Step 4: Cloudflare Load Balancer Reconfiguration

### 4a. Consolidate pools (free 2 endpoint slots)

Remove these monitoring-only pools (they don't route traffic):

- `sovereign-admin` (port 3001 health check)
- `sovereign-bridge` (port 8766 health check)

These services are still monitored via `sovereign-core` (the main HTTPS health check covers the full stack).

### 4b. Add clone to sovereign-core pool

In the `sovereign-core` pool, add a second origin:

- **Name**: `do-vps-clone`
- **Address**: CLONE_PUBLIC_IP
- **Port**: 443
- **Weight**: 1.0 (equal to primary)
- **Monitor**: `sovereign-core-health` (same as primary)

### 4c. Create sovereign-ws-primary pool

New pool for WebSocket-only traffic:

- **Pool Name**: `sovereign-ws-primary`
- **Origin Name**: `do-vps-primary-ws`
- **Address**: 68.183.168.75
- **Port**: 443
- **Monitor**: `sovereign-core-health`

### 4d. Create Custom Rule for WebSocket pinning

Use the 1 available Custom Rule slot:

- **Rule Name**: `WebSocket to primary only`
- **Condition**: `http.request.uri.path matches "^/ws"`
- **Action**: Override pool -> `sovereign-ws-primary`

### 4e. Enable Dynamic Steering

Change Traffic Steering from "Off (Failover)" to "Dynamic Steering" — this routes REST API requests to the origin with the lowest latency (measured by health checks). Since both are in SFO2, it effectively becomes round-robin with automatic failover.

### Endpoint budget after Phase 2


| Pool                 | Origins                | Endpoints Used |
| -------------------- | ---------------------- | -------------- |
| sovereign-core       | primary:443, clone:443 | 2              |
| sovereign-inference  | hetzner:11434          | 1              |
| sovereign-voice      | hetzner:8100           | 1              |
| sovereign-ws-primary | primary:443            | 1              |
| sovereign-backend    | primary:8001           | 1              |
| **Total**            |                        | **6/6**        |


### Cost


| Item                             | Monthly                                                         |
| -------------------------------- | --------------------------------------------------------------- |
| Cloudflare LB (same 6 endpoints) | $25                                                             |
| Clone VPS (2 vCPU / 4 GB)        | $24                                                             |
| **Phase 2 added cost**           | **$24**                                                         |
| **Total infrastructure**         | **~$77** (VPS $24 + clone $24 + Hetzner $28 + LB $25 - overlap) |


---

## Step 5: Verification

### 5a. Health check green across all origins

```bash
# Both VPS origins healthy
curl -sk https://68.183.168.75/health -H "Host: api.sovereignsanctuary.net"
curl -sk https://CLONE_IP/health -H "Host: api.sovereignsanctuary.net"
```

### 5b. LB routing distributes traffic

```bash
for i in {1..10}; do
  curl -s https://api.sovereignsanctuary.net/health -o /dev/null -w "%{remote_ip}\n"
done
# Should show both origin IPs
```

### 5c. WebSocket connects to primary only

Open browser DevTools, connect to `wss://api.sovereignsanctuary.net/ws`, verify it reaches the primary bridge.

### 5d. Failover test

Stop the primary's backend temporarily:

```bash
ssh root@68.183.168.75 "docker stop nate_backend"
```

Verify REST API traffic automatically routes to clone. Restart primary after test.

---

## Risks and Mitigations


| Risk                                                   | Mitigation                                                                       |
| ------------------------------------------------------ | -------------------------------------------------------------------------------- |
| Primary PostgreSQL goes down — both VPSes lose DB      | Phase 3: Add DO Managed PostgreSQL or streaming replication                      |
| Clone backend writes stale data to shared DB           | Backend is stateless (reads/writes go through PostgreSQL) — no stale writes      |
| Health check latency delay on failover                 | Dynamic Steering checks every 60s; 1-2 minutes of degraded service in worst case |
| WebSocket Custom Rule misconfigured                    | Test with `curl -v` to confirm `/ws` always routes to primary                    |
| Redis memory fills on primary (now serving 2 backends) | Monitor `redis-cli info memory`; current usage is well under the 256 MB limit    |


---

## Files to Create/Modify


| File                                         | Location    | Change                                               |
| -------------------------------------------- | ----------- | ---------------------------------------------------- |
| `docker-compose.prod.yml`                    | Primary VPS | Add VPC-bound port mappings for PostgreSQL + Redis   |
| `redis/redis.conf`                           | Primary VPS | Verify `bind` allows Docker bridge connections       |
| `docker-compose.clone.yml`                   | Clone VPS   | New file — backend + nginx only, remote DB/Redis     |
| `nginx/nginx-clone.conf`                     | Clone VPS   | Modified nginx — no WebSocket, no admin proxy        |
| `.env`                                       | Clone VPS   | Update DB/Redis connection strings to primary VPC IP |
| Cloudflare LB Dashboard                      | Cloudflare  | Pool changes, Custom Rule, Dynamic Steering          |
| `cloudflare/LOAD_BALANCER_CONFIG.md`         | Local       | Update with Phase 2 config                           |
| `.cursor/rules/cloudflare-load-balancer.mdc` | Local       | Mirror LB config changes                             |



# Cloudflare Load Balancer — Full Configuration Spec

**Hostname**: `api.sovereignsanctuary.net`
**Plan**: $25/month (6 endpoints, 1 custom rule)
**Status**: DEPLOYED — Phase 2 COMPLETE — 4 pools, 5/6 endpoints, all Healthy (Mar 14, 2026)

---

## Infrastructure Map

| Node | Public IP | VPC IP | Services | LB Role |
|---|---|---|---|---|
| DigitalOcean VPS (primary) | 68.183.168.75 | 10.120.0.2 | Full-stack API, Bridge, Admin, PostgreSQL, Redis | `sovereign-core` (weight 1.0) + `ws-primary` |
| DigitalOcean VPS (clone) | 159.65.108.25 | 10.120.0.6 | Backend only (REST API) — uses primary's DB/Redis via VPC | `sovereign-core` (weight 0.5) |
| Hetzner CAX41 | 37.27.244.80 | 10.13.13.5 (WG) | Ollama :11434, XTTS :8100 | `sovereign-inference` + `sovereign-voice` |
| Mac Twin Engine | Via Cloudflare Tunnel | — | Home GPU 70B Ollama | Not in LB (tunnel-only) |
| Sandbox VPS | 178.128.178.15 | 10.13.13.4 (WG) | Detonation chamber | Not in LB (security-only) |

**Endpoint Budget**: 6 total — **5 used** (1 available for Phase 3)

---

## VPC Peering

| Field | Value |
|---|---|
| Name | `default-nyc1--default-sfo2-1773463468472` |
| VPC A | `default-sfo2` — 10.120.0.0/20 (San Francisco) |
| VPC B | `default-nyc1` — 10.116.0.0/20 (New York) |
| Status | **Active** (established Mar 14, 2026) |
| Cost | $0 |

Any droplet in SFO2 can reach any droplet in NYC1 via private IP (and vice versa) over DigitalOcean's internal backbone. No public internet traversal, no egress fees. This enables:
- PostgreSQL streaming replication (SFO2 primary → NYC1 replica) over private IPs
- Redis state sharing across regions
- Inter-droplet health checks without public exposure

---

## 3 Monitors (Phase 2 — consolidated)

| # | Monitor | Type | Path | Port | Response Body | Host Header |
|---|---|---|---|---|---|---|
| 1 | `sovereign-core-health` | HTTPS | `/health` | 443 | `healthy` | `api.sovereignsanctuary.net` |
| 2 | `sovereign-inference-health` | HTTPS | `/health/sovereign-inference` | 443 | `models` | `api.sovereignsanctuary.net` |
| 3 | `sovereign-voice-health` | HTTP | `/health` | 8100 | (none) | (none) |

All monitors: Interval 60s, Timeout 5s, Retries 2, Expected Code 200, Follow Redirects off.

**2026-04-29 (ORANGE lockdown):** Monitor **2** MUST use HTTPS to **`https://api.sovereignsanctuary.net/health/sovereign-inference`** (GET). GREEN host nginx proxies to `http://10.13.13.5:11434/api/tags` over WireGuard. **Deprecated:** probing `http://37.27.244.80:11434` directly — ORANGE no longer exposes public `:11434`.

**Dashboard migration:** Traffic **Load Balancing** → **Health Monitors** → `sovereign-inference-health` → set Type **HTTPS**, Path **`/health/sovereign-inference`**, Port **443**, Host **`api.sovereignsanctuary.net`**, expected substring **`models`**. API automation requires a token with **Account → Load Balancers → Edit** (worker tokens often lack this scope).

`sovereign-core-health` has "Don't verify SSL/TLS certificates" checked (origin cert is hostname-based, health check connects by IP).

Monitors 4-6 (`sovereign-backend-health`, `sovereign-admin-health`, `sovereign-bridge-health`) were removed in Phase 2 to free endpoint slots. The `/health` endpoint on port 443 validates the full backend stack.

---

## 4 Pools (Phase 2 — load-balanced)

| Order | Pool | Endpoints | Address | Port | Weight | Monitor | Service |
|---|---|---|---|---|---|---|---|
| 1 | `sovereign-core` | `do-vps-primary` | 68.183.168.75 | 443 | 1.0 (67%) | `sovereign-core-health` | Full API + Bridge + Admin |
|   |                  | `do-vps-clone`   | 159.65.108.25 | 443 | 0.5 (33%) | `sovereign-core-health` | REST API only (no bridge) |
| 2 | `sovereign-inference` | `hetzner-ollama` | 37.27.244.80 | 11434 | 1.0 | `sovereign-inference-health` | Ollama 8B LLM |
| 3 | `sovereign-voice` | `hetzner-xtts` | 37.27.244.80 | 8100 | 1.0 | `sovereign-voice-health` | XTTS-v2 voice synthesis |
| 4 | `ws-primary` | `ws-primary-origin` | 68.183.168.75 | 443 | 1.0 | `sovereign-core-health` | WebSocket bridge (primary only) |

**Fallback Pool**: `sovereign-core`
**Traffic Steering**: Off (failover)

---

## Clone VPS Architecture

| Property | Value |
|---|---|
| Public IP | 159.65.108.25 |
| VPC IP | 10.120.0.6 |
| VPC | `default-sfo2` (10.120.0.0/20) |
| Compose file | `docker-compose.clone.yml` |
| Running services | Backend only (`nate_backend`) |
| Network mode | `host` (for VPC access) |
| PostgreSQL | Primary via VPC: `10.120.0.2:5432` (user: `nate_admin`) |
| Redis | Primary via VPC: `10.120.0.2:6379` |
| Nginx | Host-level, REST API only, returns 503 for `/ws` |
| WebSocket | Not available — Custom Rule routes `/ws` to `ws-primary` pool |

### Clone Nginx Config

File: `/etc/nginx/sites-enabled/clone-api`

- Port 80: HTTP health check + redirect to HTTPS
- Port 443: HTTPS reverse proxy to `localhost:8000` (FastAPI backend)
- `/ws` location: Returns 503 with JSON error (clone has no bridge)
- Uses primary's SSL certs (Cloudflare skips SSL verification)

### Clone Deployment Commands

```bash
# Start clone backend
cd /opt/clinical-sovereignty-lab
docker compose -f docker-compose.clone.yml up -d

# Check clone health
curl -sk https://159.65.108.25/health

# Check VPC connectivity to primary DB
docker run --rm --network host -e PGPASSWORD=$PG_PW postgres:15-alpine \
  psql -h 10.120.0.2 -U nate_admin -d little_nate -c 'SELECT count(*) FROM users;'
```

---

## Nginx — Sovereign inference health (primary VPS)

File: `/etc/nginx/sites-enabled/api.sovereignsanctuary.net` (443 `server` block).

Exact match location proxies Cloudflare LB probes to ORANGE over WG:

```nginx
location = /health/sovereign-inference {
    proxy_pass http://10.13.13.5:11434/api/tags;
    proxy_connect_timeout 5s;
    proxy_read_timeout 10s;
    access_log off;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
}
```

`nginx -t && systemctl reload nginx` after edits. Not duplicated in this repo — sync ops changes back to BLUE documentation when touched.

---

## Nginx Health Proxy (Primary VPS — legacy)

Config file: `/etc/nginx/sites-enabled/lb-health-monitors`

These proxy ports were used in Phase 1 for granular service monitoring. They can be disabled now that Phase 2 consolidated to the `/health` endpoint on port 443.

| Proxy Port | Target | Status |
|---|---|---|
| 8001 | `127.0.0.1:8000/health` | Can be removed (Phase 2) |
| 3001 | `127.0.0.1:3000/` | Can be removed (Phase 2) |
| 8766 | `127.0.0.1:8765/` | Can be removed (Phase 2) |

---

## Firewall Requirements

### Primary VPS (68.183.168.75)

**ufw** (droplet-level): Port 443 — ALLOW Anywhere. Ports 5432, 6379 — ALLOW from `10.120.0.0/20` (VPC clones).

**iptables DOCKER-USER**: Ports 5432, 6379 — ACCEPT from `10.120.0.0/20` (VPC clones).

**DigitalOcean Cloud Firewall** (hypervisor-level): Must allow TCP 443 inbound (Anywhere), TCP 5432 + 6379 inbound from VPC subnet (`10.120.0.0/20`).

### Clone VPS (159.65.108.25)

**ufw** (droplet-level): Port 443 — ALLOW Anywhere.

**DigitalOcean Cloud Firewall**: Must allow TCP 443 inbound (Anywhere).

### Hetzner (37.27.244.80)

**Hetzner Cloud Firewall:** TCP 22 (SSH), TCP 8100 (XTTS), UDP 51820 (WireGuard). **Remove public TCP 11434** when convenient — Ollama is WG-only on-host (`OLLAMA_HOST=10.13.13.5:11434` + `ufw`). Inference reachability for ops is `curl https://api.sovereignsanctuary.net/health/sovereign-inference` or `curl http://10.13.13.5:11434/api/tags` from GREEN over WireGuard.

---

## Traffic Steering

| Field | Value |
|---|---|
| **Steering Policy** | Off (Failover) |
| **Session Affinity** | Cookie-based, 82800s TTL |
| **Zero Downtime Failover** | Temporary |
| **Failover Across Pools** | On |
| **Endpoint Drain TTL** | 300s |

`sovereign-core` serves all REST API traffic with weighted distribution (primary 67%, clone 33%). WebSocket traffic is pinned to `ws-primary` via Custom Rule.

---

## Custom Rules (1/1 used)

### Rule: "WebSocket to Primary"

| Field | Value |
|---|---|
| **Condition** | `URI Path equals /ws` (`http.request.uri.path eq "/ws"`) |
| **Override: Terminates** | On |
| **Override: Fallback Pool** | `ws-primary` |
| **Override: Session Affinity** | By Cloudflare cookie and Client IP fallback |

This rule ensures all WebSocket upgrade requests (`/ws`) are routed exclusively to the primary VPS, which runs the WebSocket bridge (`nate_bridge`). The clone does not run a bridge and returns 503 for `/ws`. Client IP fallback ensures WebSocket connections stick even if the browser doesn't send the `__cflb` cookie on the initial upgrade request.

---

## Architecture Diagram (Phase 2)

```
                       Cloudflare Edge (302 PoPs)
                 ┌────────────────────────────────────────┐
                 │  Load Balancer                          │
   User ────────▶│  api.sovereignsanctuary.net             │
                 │                                         │
                 │  /ws → Custom Rule → ws-primary pool    │
                 │  /*  → sovereign-core (weighted)        │
                 └──┬─────────┬─────────┬──────────┬──────┘
                    │         │         │          │
           ┌───────▼──────┐  │    ┌────▼───┐  ┌───▼────┐
           │ sovereign-   │  │    │ infer  │  │ voice  │
           │ core (2 ep)  │  │    │ -ence  │  │        │
           │              │  │    │        │  │        │
           │ Primary(67%) │  │    │ Hetz   │  │ Hetz   │
           │ Clone  (33%) │  │    │ :11434 │  │ :8100  │
           └──┬───────┬───┘  │    │ Ollama │  │ XTTS   │
              │       │      │    └────────┘  └────────┘
              │       │      │
     ┌────────▼──┐  ┌─▼─────▼────┐
     │  PRIMARY  │  │   CLONE    │
     │ 68.183.   │  │ 159.65.    │
     │ 168.75    │  │ 108.25     │
     │           │  │            │
     │ Backend   │  │ Backend    │
     │ Bridge    │  │ (no bridge)│
     │ Admin     │  │            │
     │ PostgreSQL│◀─┤ VPC 10.120 │
     │ Redis     │◀─┤ .0.2←.0.6 │
     └───────────┘  └────────────┘
           ▲
           │
     ┌─────▼──────┐
     │ ws-primary │
     │ (1 ep)     │
     │ /ws only   │
     └────────────┘
```

---

## Cost Summary (Phase 2)

| Item | Monthly Cost |
|---|---|
| LB base | $5.00 |
| 5 endpoints × $2.50 | $12.50 |
| Health check origins (3 monitors) | $5.00 |
| Clone VPS (s-2vcpu-4gb-sfo2) | $24.00 |
| **Total** | **$46.50** |

---

## Phase Roadmap

### Phase 1 — Health Fleet (COMPLETE — $25/mo, Mar 14 2026)

- 6 pools, 6 monitors, 6 endpoints, all healthy
- Full fleet visibility: API, inference, voice, backend, admin, bridge
- Failover steering with sovereign-core as primary + fallback
- Email alerts on any service going unhealthy

### Phase 2 — VPS Clone + Redundancy (COMPLETE — ~$47/mo, Mar 14 2026)

- [x] VPC peering active: `default-nyc1--default-sfo2-1773463468472`
- [x] PostgreSQL (5432) and Redis (6379) exposed on primary VPC interface (`10.120.0.2`)
- [x] Primary `docker-compose.prod.yml` updated: postgres/redis services bind to VPC IP
- [x] Primary UFW + iptables: VPC subnet allowed on 5432/6379
- [x] Primary DO Cloud Firewall: VPC subnet allowed on 5432/6379
- [x] Clone snapshot from primary, deployed as `nate-vps-clone-2026-03-14-s-2vcpu-4gb-sfo2-01`
- [x] Clone configured: `docker-compose.clone.yml` — backend only, `network_mode: host`
- [x] Clone connects to primary DB/Redis via VPC (`10.120.0.2:5432`, `10.120.0.2:6379`)
- [x] Clone Nginx: REST API proxy + 503 for `/ws` (no bridge on clone)
- [x] Consolidated LB: removed `sovereign-backend`, `sovereign-admin`, `sovereign-bridge` pools
- [x] Clone added as 2nd endpoint in `sovereign-core` (weight 0.5 vs primary 1.0)
- [x] `ws-primary` pool created — primary only, for WebSocket pinning
- [x] Custom Rule: URI Path `/ws` → override to `ws-primary` pool with Client IP fallback affinity
- [x] Hetzner Cloud Firewall: SSH + Ollama + XTTS (TCP) + WireGuard (UDP 51820)
- [x] All 4 pools healthy, 5/6 endpoints used

**Result**: Weighted REST API distribution (primary 67%, clone 33%), WebSocket pinned to primary, 1 endpoint slot reserved for Phase 3.

### Phase 3 — Multi-Region + Geo Steering ($73-97/mo total)

**Trigger**: International user base or latency requirements.

**Pre-requisites completed**:
- [x] VPC peering active between SFO2 and NYC1

**Actions**:
1. Deploy NYC1 droplet from snapshot (backend + nginx only)
2. Set up PostgreSQL streaming replication: SFO2 primary → NYC1 read replica (over peered VPC — `10.120.0.x` → `10.116.0.x`)
3. NYC1 backend reads from local replica, writes forwarded to SFO2 primary
4. Add NYC1 origin to `sovereign-core` pool (3 origins total)
5. Enable **Geo Steering**: East Coast → NYC1, West Coast → SFO2
6. Add Mac Twin Engine as Cloudflare Tunnel origin if needed
7. Both VPS nodes maintain independent WireGuard tunnels to Hetzner + Mac

**Estimated cost**: LB $25-35/mo + NYC1 droplet $24-48/mo + existing

### Phase 4 — Enterprise Scale ($100+/mo)

**Trigger**: 1000+ concurrent users, multi-region compliance requirements.

**Actions**:
1. Upgrade Cloudflare plan for additional endpoints beyond 6
2. Add multiple custom rules for service-level routing:
   - `/api/voice/*` → voice-optimized pool
   - `/api/inference/*` → GPU pool
   - `/ws` → WebSocket-optimized pool with session affinity
3. Migrate to DO Managed PostgreSQL with automatic failover (private networking via VPC)
4. Add DO internal LB for regional droplet-to-droplet distribution
5. Enable Cloudflare Workers integration for edge-level request transformation

**Estimated cost**: $50-100/mo LB + compute infrastructure

---

## Verification Commands

```bash
# All active endpoints
curl -s --max-time 5 -o /dev/null -w "Primary: %{http_code}\n" https://68.183.168.75/health -k -H "Host: api.sovereignsanctuary.net"
curl -s --max-time 5 -o /dev/null -w "Clone:   %{http_code}\n" https://159.65.108.25/health -k -H "Host: api.sovereignsanctuary.net"
curl -s --max-time 5 -o /dev/null -w "Ollama:  %{http_code}\n" https://api.sovereignsanctuary.net/health/sovereign-inference
curl -s --max-time 5 -o /dev/null -w "XTTS:    %{http_code}\n" http://37.27.244.80:8100/health

# Confirm LB is routing
curl -sI https://api.sovereignsanctuary.net/health | grep -E "__cflb|server"

# Verify WebSocket routes to primary (should upgrade or get 101)
curl -sI --max-time 5 -H "Upgrade: websocket" -H "Connection: Upgrade" https://api.sovereignsanctuary.net/ws | head -5

# Verify clone rejects WebSocket
curl -sk --max-time 5 https://159.65.108.25/ws

# VPC connectivity check
ssh root@159.65.108.25 "nc -zv 10.120.0.2 5432 && echo 'PostgreSQL OK' || echo 'PostgreSQL FAIL'"
ssh root@159.65.108.25 "nc -zv 10.120.0.2 6379 && echo 'Redis OK' || echo 'Redis FAIL'"

# Check health probes in nginx logs
ssh root@68.183.168.75 "tail -5 /var/log/nginx/access.log | grep Cloudflare-Traffic-Manager"
```

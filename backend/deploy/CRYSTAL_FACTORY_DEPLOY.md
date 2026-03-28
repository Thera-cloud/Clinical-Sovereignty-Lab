# Crystal Factory Deployment Guide

Three-node crystallization network. Total cost increase: **$0**.

## Architecture

```
┌────────────────────────┐   ┌────────────────────────┐   ┌───────────────────┐
│ HETZNER (Finland)      │   │ DIGITALOCEAN (SF)      │   │ MAC (Local)       │
│ 37.27.244.80           │   │ 68.183.168.75          │   │ Existing BLUE     │
│                        │   │                        │   │                   │
│ External Factory       │   │ Internal Factory       │   │ Dev Factory       │
│ ├─ RSS feeds           │   │ ├─ 10 PG tables        │   │ ├─ Local files    │
│ ├─ GitHub trending     │   │ ├─ Clinical data       │   │ ├─ CLI output     │
│ ├─ StackOverflow       │   │ ├─ Coaching sessions   │   │ └─ Ollama 70B     │
│ │                      │   │ └─ Operations metrics  │   │                   │
│ │ Two-Stage Pipeline:  │   │                        │   │                   │
│ │ S1: Ollama 8B ($0)   │   │ Two-Stage Pipeline:    │   │                   │
│ │     score 0-10 filter│   │ S1: Ollama 8B ($0)     │   │                   │
│ │ S2: Grok (~$0.003)   │   │     via WG to Hetzner  │   │                   │
│ │     crystal synthesis│   │ S2: Grok (~$0.003)     │   │                   │
│ │                      │   │     crystal synthesis  │   │                   │
│ HIPAA: NEVER           │   │ HIPAA: YES (local)     │   │ HIPAA: NO         │
│ Crystals/day: 50-150   │   │ Crystals/day: 30-80    │   │ Crystals: 20-40   │
│ Hours/day: 24          │   │ Hours/day: 24          │   │ Hours/day: 8-12   │
└──────────┬─────────────┘   └──────────┬─────────────┘   └─────────┬─────────┘
           │ WireGuard               │ localhost                  │ Tunnel
           │                         │                            │
           └─────────────────────────┼────────────────────────────┘
                                     │
                          ┌──────────▼──────────┐
                          │ PostgreSQL           │
                          │ nate_intelligence_   │
                          │ crystals             │
                          │ (ON CONFLICT         │
                          │  content_hash        │
                          │  DO NOTHING)         │
                          └─────────────────────┘
```

## Prerequisites

### 1. Expose PostgreSQL on WireGuard Interface (DigitalOcean)

Hetzner needs to reach PostgreSQL via the WireGuard tunnel. Currently, PostgreSQL
only listens on `localhost` and the VPC interface (`10.120.0.2`).

**On DigitalOcean primary (68.183.168.75):**

```bash
# 1. Find the WireGuard interface IP (DO side of the tunnel)
ip addr show wg0 | grep inet
# Should show something like 10.13.13.1/24

# 2. Allow PostgreSQL to listen on the WG interface
# Edit docker-compose.prod.yml to add WG binding for postgres:
#   ports:
#     - "10.120.0.2:5432:5432"   # VPC (already there)
#     - "10.13.13.1:5432:5432"   # WireGuard (add this)

# 3. Allow WireGuard subnet in pg_hba.conf
docker exec nate_postgres bash -c 'echo "host little_nate nate_admin 10.13.13.0/24 md5" >> /var/lib/postgresql/data/pg_hba.conf'
docker exec nate_postgres pg_ctl reload -D /var/lib/postgresql/data

# 4. Firewall: allow port 5432 from WG subnet only
ufw allow in on wg0 to any port 5432 proto tcp

# 5. Test from Hetzner:
ssh root@37.27.244.80 "psql -h 10.13.13.1 -U nate_admin -d little_nate -c 'SELECT COUNT(*) FROM nate_intelligence_crystals'"
```

### 2. Verify WireGuard Tunnel

```bash
# From Hetzner:
ping -c 3 10.13.13.1  # Should reach DigitalOcean

# From DigitalOcean:
ping -c 3 10.13.13.5  # Should reach Hetzner
```

## Deployment

### Hetzner (External Knowledge Factory)

```bash
# 1. Copy files to Hetzner
scp backend/crystal_factory.py root@37.27.244.80:/tmp/
scp backend/.env.crystal-hetzner root@37.27.244.80:/tmp/
scp backend/deploy/crystal-factory-hetzner.service root@37.27.244.80:/tmp/
scp backend/deploy/install-crystal-factory.sh root@37.27.244.80:/tmp/

# 2. SSH into Hetzner and run installer
ssh root@37.27.244.80
mkdir -p /opt/crystal-factory
cp /tmp/crystal_factory.py /opt/crystal-factory/
cp /tmp/.env.crystal-hetzner /opt/crystal-factory/.env
cp /tmp/crystal-factory-hetzner.service /etc/systemd/system/crystal-factory.service

# 3. Set up virtualenv
python3 -m venv /opt/crystal-factory/venv
/opt/crystal-factory/venv/bin/pip install asyncpg aiohttp

# 4. Edit .env with actual password
nano /opt/crystal-factory/.env
# → Set PRODUCTION_DB_URL password

# 5. Test connectivity
/opt/crystal-factory/venv/bin/python3 -c "
import asyncio, asyncpg
async def test():
    pool = await asyncpg.create_pool('postgresql://nate_admin:PASSWORD@10.13.13.1:5432/little_nate')
    n = await pool.fetchval('SELECT COUNT(*) FROM nate_intelligence_crystals')
    print(f'Connected — {n} crystals')
    await pool.close()
asyncio.run(test())
"

# 6. Start
systemctl daemon-reload
systemctl enable crystal-factory
systemctl start crystal-factory
journalctl -u crystal-factory -f
```

### DigitalOcean (Internal Knowledge Factory)

```bash
# 1. Copy files (already on server or via scp)
mkdir -p /opt/crystal-factory
cp /opt/clinical-sovereignty-lab/backend/crystal_factory.py /opt/crystal-factory/
cp /opt/clinical-sovereignty-lab/backend/.env.crystal-digitalocean /opt/crystal-factory/.env

# 2. Set up virtualenv
python3 -m venv /opt/crystal-factory/venv
/opt/crystal-factory/venv/bin/pip install asyncpg aiohttp

# 3. Edit .env with actual password
nano /opt/crystal-factory/.env

# 4. Install + start
cp /opt/clinical-sovereignty-lab/backend/deploy/crystal-factory-digitalocean.service \
   /etc/systemd/system/crystal-factory.service
systemctl daemon-reload
systemctl enable crystal-factory
systemctl start crystal-factory
journalctl -u crystal-factory -f
```

## Two-Stage Synthesis Pipeline

Each factory cycle runs a two-stage synthesis pipeline:

| Stage | Engine | Cost | Purpose |
|---|---|---|---|
| **Stage 1** | Ollama 8B (local or via WG) | $0 | Score fragments 0-10 for relevance, keep >= 6 |
| **Stage 2** | Grok (Azure Foundry) | ~$0.003/cycle | Synthesize top clusters into high-quality crystals |

**Fallback chain**: If Grok is unreachable, falls back to Ollama synthesis (lower quality). If Ollama is also unreachable, raw fragment concatenation is used (last resort, logged as warning).

### Source-Based Confidence

Crystals receive initial confidence based on their source material:

| Source | Confidence | Rationale |
|---|---|---|
| `nevedal_metrics` | 0.70 | Real coherence engine data |
| `conversation_history` | 0.68 | Actual therapy sessions |
| `live_session` | 0.68 | Coach session summaries |
| `wisdom_extraction` | 0.65 | Approved wisdom entries |
| `coach_briefing` | 0.65 | Coaching analysis |
| `classroom_analysis` | 0.63 | Classroom session analysis |
| `transfer_crystal` | 0.62 | Imported AI memories |
| `vault_document` | 0.58 | Uploaded documents |
| `stackoverflow` | 0.58 | Community-vetted Q&A |
| `rss_*` / `github_trending` | 0.53-0.55 | Public content |

Final confidence = weighted average of sources + cluster size bonus (capped at 0.85).

### Grok Credentials

Same credentials as the production inference router (`nate_ai_config.py`):

```bash
GROK_URL=https://nathanlhr-0393-resource.services.ai.azure.com/models/chat/completions?api-version=2024-05-01-preview
GROK_API_KEY=<from NATE_CHAT_KEY in production .env>
GROK_MODEL=grok-4-1-fast-non-reasoning
```

## Monitoring

### Network Dashboard (recommended)

Run from any machine with DB access to see all three nodes at once:

```bash
# From Mac (BLUE server):
PRODUCTION_DB_URL=postgresql://nate_admin:PASSWORD@68.183.168.75:5432/little_nate \
  python3 backend/crystal_factory.py --status

# From DigitalOcean (localhost):
PRODUCTION_DB_URL=postgresql://nate_admin:PASSWORD@localhost:5432/little_nate \
  python3 /opt/crystal-factory/crystal_factory.py --status

# From Hetzner (via WireGuard):
PRODUCTION_DB_URL=postgresql://nate_admin:PASSWORD@10.13.13.1:5432/little_nate \
  python3 /opt/crystal-factory/crystal_factory.py --status
```

Example output:

```
╔════════════════════════════════════════════════════════════════════════════════════╗
║                    Crystal Factory Network — Live Status                          ║
╠════════════════════════════════════════════════════════════════════════════════════╣
║                                                                                   ║
║  Node             Hrs/day  Sources            24h    7d   Total  Domains           ║
║  ────────────────────────────────────────────────────────────────────────────────  ║
║  Hetzner               24  RSS, GitHub, SO     87   610    1204  coding, general   ║
║  DigitalOcean           24  10 PG tables        52   364     891  clinical, coach   ║
║  Mac (BLUE)           8-12  Local dev           24   168     445  coding, deploy    ║
║  ────────────────────────────────────────────────────────────────────────────────  ║
║  TOTAL                                        163  1142    2540  All domains        ║
║                                                                                   ║
╚════════════════════════════════════════════════════════════════════════════════════╝
```

### Manual Queries

```bash
# Live logs
journalctl -u crystal-factory -f

# Crystal count growth
psql -U nate_admin -d little_nate -c "
  SELECT face_path, COUNT(*) as crystals, MIN(created_at)::date as first, MAX(created_at)::date as last
  FROM nate_intelligence_crystals
  WHERE face_path LIKE 'factory:%'
  GROUP BY face_path
  ORDER BY crystals DESC
"

# Watermark status (when did each node last harvest?)
psql -U nate_admin -d little_nate -c "
  SELECT node_id, last_harvest, crystals_total
  FROM crystal_factory_watermarks
  ORDER BY last_harvest DESC
"

# Crystals per day per node
psql -U nate_admin -d little_nate -c "
  SELECT face_path, created_at::date as day, COUNT(*)
  FROM nate_intelligence_crystals
  WHERE face_path LIKE 'factory:%'
  GROUP BY face_path, day
  ORDER BY day DESC, face_path
  LIMIT 20
"

# Factory heartbeats (health monitoring)
psql -U nate_admin -d little_nate -c "
  SELECT DISTINCT ON (node_id)
      node_id, cycle_number, crystals_forged, fragments_harvested,
      elapsed_seconds, created_at,
      (created_at > NOW() - INTERVAL '60 minutes') AS healthy
  FROM crystal_factory_heartbeats
  ORDER BY node_id, created_at DESC
"

# Stage pipeline performance (last 10 cycles)
psql -U nate_admin -d little_nate -c "
  SELECT node_id, cycle_number, fragments_harvested, stage1_filtered AS passed_filter,
         clusters_formed, stage2_synthesized, crystals_forged, crystals_deduped,
         round(elapsed_seconds::numeric, 1) AS secs, created_at
  FROM crystal_factory_heartbeats
  ORDER BY created_at DESC
  LIMIT 10
"
```

### Health Alert Integration

The `crystal_factory_heartbeats` table supports the bridge health gate. A node is
**unhealthy** if its most recent heartbeat is older than 60 minutes (1 harvest cycle).
The `check_factory_health()` method on `CrystalDB` returns per-node status for
integration with the bridge's autonomous health gate.

## How the Three Nodes Avoid Duplicates

All three write to the same `nate_intelligence_crystals` table:

| Mechanism | How |
|---|---|
| `content_hash` UNIQUE constraint | SHA-256 of crystal text — identical crystals are rejected |
| `ON CONFLICT DO NOTHING` | Silent dedup, no errors |
| `face_path` column | Tracks origin: `factory:hetzner-finland`, `factory:digitalocean-primary` |
| Domain separation | External=coding/general, Internal=clinical/coaching, Dev=coding/deployment |

## HIPAA Compliance

| Data Type | Hetzner sees it? | DigitalOcean sees it? |
|---|---|---|
| RSS feed articles | YES | NO |
| GitHub trending repos | YES | NO |
| StackOverflow questions | YES | NO |
| conversation_history | **NEVER** | YES (localhost) |
| coaching_sessions | **NEVER** | YES (localhost) |
| nevedal_metrics | **NEVER** | YES (localhost) |
| vault_item_annotations | **NEVER** | YES (localhost) |

The external factory on Hetzner has no harvest queries that touch clinical tables.
It writes crystals TO the production database, but only reads external web sources.

## Cost Impact

| Item | Before | After |
|---|---|---|
| Hetzner CAX41 | $28/mo (already running) | $28/mo (same) |
| DigitalOcean VPS | $48/mo (already running) | $48/mo (same) |
| Mac electricity | ~$10/mo (already running) | ~$10/mo (same) |
| Grok synthesis (Azure Foundry) | $0 | ~$2-4/mo (48 cycles/day x ~$0.003/cycle) |
| **Crystal output** | **0-30/day** (BLUE only, 8-12h) | **100-270/day** (3 nodes, 24h) |

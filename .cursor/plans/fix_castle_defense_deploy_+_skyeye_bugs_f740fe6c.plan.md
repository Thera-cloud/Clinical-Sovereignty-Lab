---
name: Fix Castle Defense Deploy + SkyEye Bugs
overview: Fix the Castle Defense WireGuard mesh deployment (MacBook WireGuard install, production firewall, detonation sandbox, Mirror VPS access) and fix two SkyEye session engine bugs that are blocking all content creation on every platform.
todos:
  - id: skyeye-fix-create-phase
    content: "Fix _create_phase bug: change approved.get(\"expressions\", []) to approved in skyeye_session_engine.py line 632"
    status: completed
  - id: skyeye-fix-session-record
    content: "Fix session record bug: remove json.dumps() wrapper on platforms_visited in skyeye_session_engine.py line 974"
    status: completed
  - id: skyeye-deploy
    content: Deploy fixed skyeye_session_engine.py to production and restart nate_backend
    status: completed
  - id: macbook-wireguard
    content: Install WireGuard on MacBook and bring up wg0 tunnel
    status: completed
  - id: verify-mesh
    content: Verify WireGuard mesh connectivity (MacBook <-> Production, MacBook <-> Mirror, MacBook <-> Sandbox)
    status: completed
  - id: mirror-ssh-access
    content: Regain SSH to Mirror VPS via MacBook WireGuard tunnel (port 2222)
    status: completed
  - id: production-ufw
    content: Enable UFW on production server with proper rules for SSH, HTTP, HTTPS, WireGuard
    status: completed
  - id: detonation-sandbox
    content: Start detonation sandbox container via docker compose --profile security
    status: completed
  - id: final-verification
    content: "Verify: UFW active, mesh connected, honeypot running, sandbox healthy, SkyEye posting"
    status: completed
isProject: false
---

# Fix Castle Defense Deployment + SkyEye Content Creation Bugs

## Current State

### Castle Defense (WireGuard Mesh)

The terminal commands failed because server-side commands (`ufw`, `iptables`, `docker compose`) were run locally on the MacBook instead of on the production server via SSH.

**What's working:**

- WireGuard IS running on production (68.183.168.75) with 3 peers configured
- Production <-> Mirror VPS (165.227.19.117 / 10.13.13.3): connected, handshakes active
- Production <-> Sandbox VPS (178.128.178.15 / 10.13.13.4): connected, handshakes active
- Production <-> MacBook: peer configured but **no handshake** (MacBook WireGuard not installed)

**What's broken:**

- **MacBook WireGuard not installed** -- the MacBook peer has no endpoint or handshake on production
- **Mirror VPS locked out** -- Phase 1 + lockdown both ran: SSH moved to port 2222 on WireGuard-only, port 22 is the honeypot. Can't SSH in because production server's key isn't authorized, and MacBook WireGuard tunnel isn't up
- **Production UFW inactive** -- `ufw status` returns "inactive"
- **Detonation sandbox not deployed** -- `/opt/detonation-sandbox/` doesn't exist on production. The sandbox service lives in [docker-compose.yml](docker-compose.yml) under `profiles: [security]` (line 206), not a separate compose file

### SkyEye Session Engine Bugs

Two bugs are blocking Little Nate from creating or posting content on ALL platforms (X, YouTube, Facebook, etc.):

**Bug 1: `'list' object has no attribute 'get'` in `_create_phase**`

In [backend/app/services/skyeye_session_engine.py](backend/app/services/skyeye_session_engine.py) line 630-632:

```python
approved = await expr_service.get_approved_expressions(limit=3)
unposted = [
    e for e in approved.get("expressions", [])  # BUG: approved is a list, not a dict
    if not e.get("posted")
]
```

`get_approved_expressions()` in [backend/app/services/skyeye_expressions.py](backend/app/services/skyeye_expressions.py) returns `List[Dict]` (line 114), but the code treats it as a dict with `.get("expressions", [])`. This crashes every `_create_phase` call, preventing ALL content creation.

**Fix:** Change `approved.get("expressions", [])` to just `approved`.

**Bug 2: `json.dumps()` on PostgreSQL array column**

In [backend/app/services/skyeye_session_engine.py](backend/app/services/skyeye_session_engine.py) line 974:

```python
json.dumps(platforms_visited),  # BUG: passes JSON string to TEXT[] column
```

asyncpg expects a Python list for PostgreSQL array columns, not a JSON-encoded string.

**Fix:** Remove `json.dumps()` wrapper, pass `platforms_visited` directly.

---

## Execution Plan

### Part A: SkyEye Session Engine Fixes (code changes)

1. Fix `_create_phase` in `skyeye_session_engine.py` line 632: change `approved.get("expressions", [])` to `approved`
2. Fix `_rest_phase` in `skyeye_session_engine.py` line 974: change `json.dumps(platforms_visited)` to `platforms_visited`
3. Deploy both fixes to production via `scp` and restart `nate_backend`
4. Verify the "Create phase error" messages stop in container logs

### Part B: Castle Defense Deployment

**Step 1: Install WireGuard on MacBook**

```bash
brew install wireguard-tools
sudo mkdir -p /etc/wireguard
sudo cp wireguard/macbook/wg0.conf /etc/wireguard/wg0.conf
sudo chmod 600 /etc/wireguard/wg0.conf
sudo wg-quick up wg0
```

This brings up the MacBook peer (10.13.13.1) and establishes tunnels to production (10.13.13.2) and Mirror VPS (10.13.13.3).

**Step 2: Verify mesh connectivity**

```bash
ping -c 2 10.13.13.2  # MacBook -> Production
ping -c 2 10.13.13.3  # MacBook -> Mirror VPS
ping -c 2 10.13.13.4  # MacBook -> Sandbox VPS
```

**Step 3: Regain Mirror VPS SSH access**

Once MacBook WireGuard is up, SSH from MacBook (whose key is authorized):

```bash
ssh -p 2222 root@10.13.13.3
```

Verify honeypot and services are healthy.

**Step 4: Enable production UFW** (run via SSH on 68.183.168.75)

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment "SSH"
ufw allow 80/tcp comment "HTTP"
ufw allow 443/tcp comment "HTTPS"
ufw allow 51820/udp comment "WireGuard"
ufw allow from 10.13.13.0/24 comment "WireGuard mesh"
echo "y" | ufw enable
```

Plus Docker iptables rule:

```bash
iptables -I DOCKER-USER -s 10.13.13.0/24 -j ACCEPT
```

**Step 5: Deploy detonation sandbox** (run via SSH on 68.183.168.75)

The sandbox is defined in the main `docker-compose.yml` with `profiles: [security]`. To start it:

```bash
cd /opt/clinical-sovereignty-lab
docker compose --profile security up -d detonation
```

No need for `/opt/detonation-sandbox/` -- it's in the main compose stack.

**Step 6: Verify everything**

- Production UFW active
- WireGuard mesh fully connected (all 4 peers)
- Mirror VPS honeypot running
- Detonation sandbox container healthy
- SkyEye content creation working (no more `'list' object has no attribute 'get'` errors)


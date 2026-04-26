# BLUE Node — Classroom Visual Server (Apple GPU)

`classroom_visual_server.py` is the Mac-side companion to GREEN's
`classroom_remote_dispatch.remote_visual_frames()`. When
`CLASSROOM_VISUAL_REMOTE_URL` is set in `docker-compose.prod.yml`,
GREEN hands the visual frame extraction + analysis to this Mac so the
6 GB DigitalOcean VPS doesn't have to run cv2/moviepy on long videos.

See `.cursor/rules/cloudflare-tunnel-twin-engine.mdc` for the full
Twin Engine architecture.

## One-time install

```bash
# 1. Vendor the backend tree somewhere stable on this Mac
mkdir -p ~/SovereignSanctuary
rsync -av --delete \
    ~/Desktop/Clinical-Sovereignty-Lab-2/backend/ \
    ~/SovereignSanctuary/clinical-sovereignty-lab/backend/

# 2. Create the venv used by the LaunchDaemon
cd ~/SovereignSanctuary/clinical-sovereignty-lab
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install fastapi uvicorn[standard] httpx pydantic \
    opencv-python numpy moviepy

# Optional but recommended for moviepy on Apple Silicon
brew install ffmpeg

# 3. Generate / record the shared bearer (must match GREEN + ORANGE)
TOKEN=$(openssl rand -hex 32)
echo "$TOKEN"  # save this — paste into the LaunchDaemon plist below
              # and into GREEN's .env (CLASSROOM_REMOTE_AUTH_TOKEN)
              # and into /etc/sovereign/voice_emotion.env on ORANGE

# 4a. Install as a LaunchAgent (no sudo, runs at login — recommended)
mkdir -p ~/Library/LaunchAgents ~/Library/Logs/Sovereign
# Render the plist with the bearer baked in (token kept off git in
# ~/.sovereign/classroom_remote_bearer.txt, mode 0600).
BEARER="$(cat ~/.sovereign/classroom_remote_bearer.txt)"
# (the activation transcript writes ~/Library/LaunchAgents/com.sovereignsanctuary.classroom-visual.plist
#  programmatically; see the deploy script in this repo.)
launchctl load -w ~/Library/LaunchAgents/com.sovereignsanctuary.classroom-visual.plist

# 4b. (Alternative) Install as a system LaunchDaemon (survives without
#     a logged-in user — needs sudo). Use the template plist in this
#     directory and edit CLASSROOM_REMOTE_AUTH_TOKEN before copying.
# sudo mkdir -p /var/log/sovereign
# sudo cp com.sovereignsanctuary.classroom-visual.plist /Library/LaunchDaemons/
# sudo chown root:wheel /Library/LaunchDaemons/com.sovereignsanctuary.classroom-visual.plist
# sudo chmod 644       /Library/LaunchDaemons/com.sovereignsanctuary.classroom-visual.plist
# sudo launchctl bootstrap system /Library/LaunchDaemons/com.sovereignsanctuary.classroom-visual.plist

# 5. Verify
curl -s http://127.0.0.1:8200/health | python3 -m json.tool
```

## Cloudflare Tunnel route

The Twin Engine tunnel (`d40e5315-4d8a-44b8-a432-debc36750636`) already
exposes Ollama on port `11434` via the `overseer-manifold` VPC service.
Add a sibling route for the visual server:

1. Cloudflare Dashboard → Zero Trust → Networks → Tunnels → "Little Nate
   Twin Engine" → Public Hostnames → Add a public hostname
   - Subdomain: `classroom-visual`
   - Domain: `internal.sovereignsanctuary.net` (or another zone)
   - Type: HTTP
   - URL: `localhost:8200`
2. Lock it behind Cloudflare Access with a service-token policy so only
   GREEN can reach it.
3. On GREEN, set:
   ```
   CLASSROOM_VISUAL_REMOTE_URL=https://classroom-visual.internal.sovereignsanctuary.net
   CF-Access-Client-Id   / CF-Access-Client-Secret  (if using service tokens)
   ```
   `classroom_remote_dispatch.remote_visual_frames()` already sends the
   `Authorization: Bearer <CLASSROOM_REMOTE_AUTH_TOKEN>` header — the
   Cloudflare Access service-token headers can be added as a future
   refinement (the dispatch helper has a single `_auth_headers()` slot
   that's easy to extend).

## Update flow

After editing `classroom_visual_server.py` here on BLUE:

```bash
rsync -av --delete \
    ~/Desktop/Clinical-Sovereignty-Lab-2/backend/scripts/blue/ \
    ~/SovereignSanctuary/clinical-sovereignty-lab/backend/scripts/blue/
sudo launchctl kickstart -k system/com.sovereignsanctuary.classroom-visual
curl -s http://127.0.0.1:8200/health | python3 -m json.tool
```

## Why BLUE owns this

Per `cloudflare-tunnel-twin-engine.mdc` rule #4:

> **Apple Silicon GPU memory is shared.** Running Ollama 70B (~40GB) and
> XTTS-v2 (~2GB) simultaneously requires ~42GB of unified memory…

A 5-frame visual pass on a 1h52m video uses < 500 MB and finishes in
seconds, so it co-exists comfortably with Ollama 70B. GREEN attempting
the same would consume cv2 buffers on top of the 100+ Python services
in its 6 GB cgroup — exactly what OOM-killed the recovery run.

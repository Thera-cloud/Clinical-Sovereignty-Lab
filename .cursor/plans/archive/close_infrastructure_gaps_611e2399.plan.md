---
name: Close Infrastructure Gaps
overview: "Fix 5 infrastructure gaps: create missing Vectorize index, add missing docker-compose env vars, implement user-selectable TTS voice routing, deploy all 8 Cloudflare Edge Workers for the first time, and repair Hetzner SSH access from production."
todos:
  - id: gap1-vectorize-index
    content: Create nate-predictive Vectorize index via Cloudflare API call from production VPS
    status: completed
  - id: gap2-compose-vars
    content: Add CLOUDFLARE_META_TOKEN, CLOUDFLARE_TOKEN_ID, D1_DATABASE_ID to docker-compose.prod.yml backend environment block; set D1_DATABASE_NAME in .env
    status: completed
  - id: gap3-tts-preference
    content: Add tts_provider_preference to profile_data, wire into bridge TTS handler and VoiceRouter, add settings WebSocket handler, set SOVEREIGN_TTS_URL in .env
    status: completed
  - id: gap4-worker-deploy
    content: Authenticate wrangler, set secrets, deploy all 8 Cloudflare Edge Workers from Mac, verify each is active
    status: completed
  - id: gap5-hetzner-ssh
    content: Diagnose and fix SSH key auth from production VPS (68.183.168.75) to Hetzner (37.27.244.80), verify WireGuard tunnel, test full jump chain
    status: completed
isProject: false
---

# Close Infrastructure Gaps (5 Fixes)

## GAP 1: Create Missing `nate-predictive` Vectorize Index

The code in [backend/app/services/vectorize_service.py](backend/app/services/vectorize_service.py) defines 7 indexes (line 56-64), but Cloudflare only has 6. The `nate-predictive` index (cycle detections, foresight alerts) was never created.

- Run a single Cloudflare API call from the production VPS to create the index:

```
  POST /accounts/{account_id}/vectorize/v2/indexes
  {"name":"nate-predictive","config":{"dimensions":1024,"metric":"cosine"}}
  

```

- Verify with `GET /vectorize/v2/indexes` that all 7 indexes now appear

## GAP 2: Add Missing Env Vars to `docker-compose.prod.yml`

Three vars are in `.env` but not explicitly passed through the compose `environment:` block. Per project rules, this makes them fragile against `load_dotenv(override=True)` regressions.

Add to the **backend** service `environment:` block in [docker-compose.prod.yml](docker-compose.prod.yml):

```yaml
- CLOUDFLARE_META_TOKEN=${CLOUDFLARE_META_TOKEN:-}
- CLOUDFLARE_TOKEN_ID=${CLOUDFLARE_TOKEN_ID:-}
- D1_DATABASE_ID=${D1_DATABASE_ID:-}
```

Also set `D1_DATABASE_NAME=nate-edge-db` in the production `.env` (cosmetic but completes the config).

Recreate backend container after changes.

## GAP 3: User-Selectable TTS Voice (XTTS vs Edge TTS)

**Current architecture** (two separate paths):

- **VoiceRouter** (`voice_router.py`): XTTS -> Edge TTS -> Workers AI (for REST/realtime)
- **Bridge** (`bridge_server.py`): Azure Mini-TTS -> Azure Realtime only (WebSocket chat)

**Plan**: Add a `tts_provider_preference` field to user `profile_data` with values: `"auto"` (default -- Edge TTS), `"sovereign"` (XTTS cloned voice), `"azure"` (premium Azure voice).

Changes needed:

- **Bridge** (`bridge_server.py`, `_handle_tts_speak`): Before calling Azure Mini-TTS, check `profile_data.get("tts_provider_preference", "auto")`. If `"sovereign"`, call `sovereign_tts.synthesize()` first, fall back to Edge TTS, then Azure. If `"auto"`, use Edge TTS -> Azure fallback.
- **VoiceRouter** (`voice_router.py`, `_tts`): Accept an optional `provider_preference` param. If `"sovereign"`, prioritize XTTS tier. If `"auto"`, skip XTTS (save Hetzner RAM) and go straight to Edge TTS.
- **Settings handler** in bridge: Add a `update_tts_preference` WebSocket handler that sets `profile_data.tts_provider_preference`.
- **Re-enable XTTS conditionally**: Set `SOVEREIGN_TTS_URL=http://10.13.13.5:8100` in `.env` but keep XTTS stopped by default. Only start it when at least one user has `"sovereign"` preference (manual toggle for now).
- **Flutter settings screen**: Add a TTS voice selector (Auto / Sovereign Voice / Premium) in the existing settings gear.

## GAP 4: Deploy All 8 Cloudflare Edge Workers (First-Time)

Workers are deployed from the user's Mac via `npx wrangler deploy`, not from the VPS. This requires:

**Step 1: Authenticate wrangler**

```bash
npx wrangler login
```

This opens a browser OAuth flow to authorize wrangler with the Cloudflare account.

**Step 2: Set secrets** (before deploying workers that need them)

```bash
cd cloudflare/workers/nate-summon-worker
npx wrangler secret put HMAC_SECRET

cd cloudflare/workers/nate-webhook-gateway
npx wrangler secret put STRIPE_WEBHOOK_SECRET
npx wrangler secret put TWILIO_AUTH_TOKEN
npx wrangler secret put ZOOM_WEBHOOK_SECRET
```

**Step 3: Deploy all 8 workers** (order matters -- deploy workers without route bindings first):

```bash
cd cloudflare/workers/r2-cdn && npx wrangler deploy
cd cloudflare/workers/nate-analytics-edge && npx wrangler deploy
cd cloudflare/workers/nate-auth-edge && npx wrangler deploy
cd cloudflare/workers/nate-webhook-gateway && npx wrangler deploy
cd cloudflare/workers/nate-voice-edge && npx wrangler deploy
cd cloudflare/workers/nate-cron-worker && npx wrangler deploy
cd cloudflare/workers && npx wrangler deploy                # nate-edge-cache
cd cloudflare/workers/nate-summon-worker && npx wrangler deploy
```

**Step 4: Verify** each worker is active:

```bash
npx wrangler deployments list --name nate-summon-worker
# Repeat for each worker
```

**Route conflicts to watch**: `nate-edge-cache` and `nate-summon-worker` both bind to `api.sovereignsanctuary.net` routes. Ensure no route overlap (summon uses `/api/summon/`*, edge-cache uses other `/api/`* paths).

**DNS requirement**: `cdn.sovereignsanctuary.net` must have a CNAME or proxied A record in Cloudflare DNS for the R2 CDN worker routes.

## GAP 5: Fix Hetzner SSH from Production VPS

SSH from `68.183.168.75` to `37.27.244.80` fails with `Permission denied (publickey,password)`.

- Check if the production VPS root SSH key exists: `ls -la /root/.ssh/id_`* on `68.183.168.75`
- If the key exists, check if it's in Hetzner's `authorized_keys`: `ssh root@37.27.244.80` (try from Mac first to verify Hetzner is reachable)
- If the key is missing or wrong, generate a new one on production VPS and add its public key to Hetzner's `/root/.ssh/authorized_keys`
- Also verify WireGuard tunnel is still up: `ping -c 2 10.13.13.5` from production VPS
- If WireGuard is up, test SSH over WireGuard: `ssh root@10.13.13.5` (this may work even if public IP SSH fails)
- After fixing, verify the full jump chain: `ssh root@68.183.168.75 "ssh root@10.13.13.5 hostname"`


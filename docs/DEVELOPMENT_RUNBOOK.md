# Development Runbook (Clinical Sovereignty Lab / Little Nate)

This is the practical “how we run it” guide for local development + the current single-droplet production setup.

## Local dev (Mac)

### Flutter (web)

- **Run (recommended)**: let Flutter choose a free port (avoids stale asset/font issues).

```bash
cd ~/Desktop/Clinical-Sovereignty-Lab-2/mobile
flutter clean
flutter pub get
flutter run -d chrome --web-hostname 127.0.0.1 --web-port 0
```

- **Production WS override in browser** (for local Flutter web connecting to prod):
  - `ws` override is supported by `defaultWsUrl` parsing.
  - Example URL:  
    `http://127.0.0.1:<port>/#/?ws=wss%3A%2F%2Fapi.sovereignsanctuary.net%2Fws`

### Backend (local)

If you run backend locally, prefer a `.venv` and keep all secrets in `.env` (never commit secrets).

## Production (single droplet)

### Current service layout

- **Droplet**: `68.183.168.75`
- **API + WS**: Docker Compose on droplet
  - FastAPI backend: `127.0.0.1:8000`
  - Bridge (WebSocket): `127.0.0.1:8765`
  - Nginx terminates TLS and proxies:
    - `/` → backend
    - `/ws` → bridge

### Data mounts (bind mounts)

From `docker-compose.prod.yml`:
- backend data: `/opt/clinical-sovereignty-lab/data/backend` → container `/app/data`
- bridge data: `/opt/clinical-sovereignty-lab/data/bridge` → container `/app/data`
- bridge reads backend scheduling store:
  - `/opt/clinical-sovereignty-lab/data/backend` → container `/app/backend_data` (read-only)

## Deploying code changes to the droplet

### Backend/bridge code

From your Mac (example):

```bash
rsync -av \
  ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket/bridge_server.py \
  root@68.183.168.75:/opt/clinical-sovereignty-lab/backend/app/websocket/bridge_server.py

rsync -av \
  ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/routers/sessions.py \
  root@68.183.168.75:/opt/clinical-sovereignty-lab/backend/app/routers/sessions.py
```

Then on the droplet:

```bash
cd /opt/clinical-sovereignty-lab
docker compose -f docker-compose.prod.yml build --no-cache bridge backend
docker compose -f docker-compose.prod.yml up -d --force-recreate bridge backend
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=100 bridge
docker compose -f docker-compose.prod.yml logs --tail=100 backend
```

## Hosting Flutter web on the droplet (Option A: `app.` subdomain)

### DNS

Keep Squarespace on root + `www`. Create:
- **A** record: `app` → `68.183.168.75`

Verify:

```bash
dig +short app.sovereignsanctuary.net
```

### Nginx + TLS (Certbot)

On droplet:

1) HTTP site first (so `nginx -t` passes):

```bash
mkdir -p /var/www/sovereignsanctuary-web
chown -R www-data:www-data /var/www/sovereignsanctuary-web

cat > /etc/nginx/sites-available/app.sovereignsanctuary.net <<'EOF'
server {
  listen 80;
  server_name app.sovereignsanctuary.net;

  location /.well-known/acme-challenge/ {
    root /var/www/certbot;
  }

  location / {
    root /var/www/sovereignsanctuary-web;
    try_files $uri $uri/ /index.html;
  }
}
EOF

ln -sf /etc/nginx/sites-available/app.sovereignsanctuary.net /etc/nginx/sites-enabled/app.sovereignsanctuary.net
nginx -t && systemctl reload nginx
```

2) Then TLS:

```bash
certbot --nginx -d app.sovereignsanctuary.net
nginx -t && systemctl reload nginx
```

### Build + upload Flutter web (release)

On your Mac:

```bash
cd ~/Desktop/Clinical-Sovereignty-Lab-2/mobile
flutter clean
flutter pub get
flutter build web --release --base-href /
```

Upload from your Mac (not from the droplet):

```bash
rsync -av --delete \
  ~/Desktop/Clinical-Sovereignty-Lab-2/mobile/build/web/ \
  root@68.183.168.75:/var/www/sovereignsanctuary-web/
```

## Zoom scheduling (production)

### Sanity checks

- Check runtime flag:

```bash
docker exec -it nate_backend sh -lc 'python -c "from app.config import settings; print(settings.ENABLE_ZOOM)"'
```

- Schedule test (use a time that doesn’t conflict):

```bash
curl -sS -X POST http://127.0.0.1:8000/api/sessions/schedule \
  -H "Content-Type: application/json" \
  -d '{
    "client_id":"CLIENT_TEST",
    "coach_id":"COACH_001",
    "family_id":"FAM_TEST",
    "client_name":"John & Jane",
    "scheduled_start":"2030-01-01T23:00:00Z",
    "scheduled_end":"2030-01-01T23:50:00Z",
    "session_type":"COACH",
    "notes":"Zoom auto-create test",
    "zoom_link":""
  }'
```

## Coach learning → Admin approvals → Night School

### Flow

1) Coach starts a live session.
2) Coach sends at least one note.
3) Coach ends live session with `share_with_nate: true`.
4) Bridge enqueues a learning item (PENDING unless auto-approved).
5) Admin approves/rejects in Admin “LEARNING” tab.

### Files (bridge data)

- Queue: `/opt/clinical-sovereignty-lab/data/bridge/coach_learning_queue.json`
- Archive: `/opt/clinical-sovereignty-lab/data/bridge/coach_learning_archive.json`

### Retention controls (bridge env vars)

Set these in droplet `.env` if desired (safe defaults exist in code):
- `COACH_LEARNING_RETENTION_DAYS` (default `90`)
- `COACH_LEARNING_QUEUE_MAX_ITEMS` (default `2000`)
- `COACH_LEARNING_ARCHIVE_MAX_ITEMS` (default `20000`)
- `COACH_LIVE_SESSIONS_MAX_ENDED` (default `500`)

## Common troubleshooting

### “X boxes” instead of icons (Flutter web)

If you see missing glyph boxes and logs mention `assets/FontManifest.json` missing:
- Ensure `mobile/web/index.html` has `<base href="/">`
- Use **random port** in dev (`--web-port 0`) to avoid stale dev-server state
- Hard refresh + clear service worker/site data

### Certbot unauthorized / 404

If Let’s Encrypt shows `unauthorized` or points to Squarespace IPs:
- DNS isn’t pointing at the droplet
- Fix DNS first, then rerun certbot

## Backups

We keep timestamped backups under `backups/`.
Example: `backups/20260202_030943/`


## login help

ssh root@68.183.168.75
https://app.sovereignsanctuary.net/#/?ws=wss%3A%2F%2Fapi.sovereignsanctuary.net%2Fws

## RESTART BRIDGE COMMANDS AFTER BUILD CHANGES

cd /opt/clinical-sovereignty-lab

docker compose -f docker-compose.prod.yml ps

# restart just the bridge container
docker compose -f docker-compose.prod.yml restart bridge

# follow logs to confirm it came up clean
docker compose -f docker-compose.prod.yml logs -f --tail=200 bridge


## IF YOU CHANGE BRIDGE AND NEED TO CONTAINER TO REBUILD

cd /opt/clinical-sovereignty-lab
docker compose -f docker-compose.prod.yml up -d --build bridge
docker compose -f docker-compose.prod.yml logs -f --tail=200 bridge

## How to get your terminal back

## first-best practice
cd /opt/clinical-sovereignty-lab
docker compose -f docker-compose.prod.yml up -d --build bridge

## second-confirm its healthy
cd /opt/clinical-sovereignty-lab
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=200 bridge

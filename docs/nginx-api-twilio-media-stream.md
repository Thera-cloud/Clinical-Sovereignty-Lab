# Nginx: Twilio Media Stream (`/ws/nate-media-stream`)

Twilio opens:

`wss://api.sovereignsanctuary.net/ws/nate-media-stream`

to the **FastAPI backend** (same process as `/api/*`, typically port **8000**). It must **not** be proxied to the **bridge** WebSocket (`/ws` → port **8765**), which is for Flutter `login_request` / app traffic.

## Production (DigitalOcean host nginx)

In the `server { server_name api.sovereignsanctuary.net; ... }` block, define **`/ws/nate-media-stream` before** the generic `location /ws` so the more specific route wins.

```nginx
# Twilio Media Stream → backend (uvicorn/FastAPI on localhost:8000)
location = /ws/nate-media-stream {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_connect_timeout 75s;
    proxy_send_timeout 86400s;
    proxy_read_timeout 86400s;
}

# Existing: Flutter bridge
location /ws {
    proxy_pass http://127.0.0.1:8765;
    # ... Upgrade + Connection + long timeouts ...
}
```

### Why `proxy_read_timeout 86400`

Without an explicit long timeout, nginx often defaults to **60s** and **closes the WebSocket**, which drops **every voice call** after about one minute.

### Verify after deploy

```bash
# From laptop (expect 404/403 from app without Twilio handshake — not 502 from wrong upstream)
curl -sI -H 'Connection: Upgrade' -H 'Upgrade: websocket' \
  'https://api.sovereignsanctuary.net/ws/nate-media-stream'
```

Check access/error logs while placing a test call: upstream should be **8000**, not **8765**.

## Docker Compose

See `nginx/nginx.conf` — `api.sovereignsanctuary.net` includes the same `location = /ws/nate-media-stream` → `api_servers` (backend container).

# Deploy: Classroom Lived Wisdom + Bridge Fix + UX Plan Updates

Run from project root. **Never use rsync --delete.**

## 1. Backend + migration (scp)

```bash
SERVER="root@68.183.168.75"
PROJECT="/opt/clinical-sovereignty-lab"
LOCAL="/Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2"

# Bridge + PG helpers + sessions + coach router
scp "$LOCAL/backend/app/websocket/bridge_server.py" "$SERVER:$PROJECT/backend/app/websocket/"
scp "$LOCAL/backend/app/services/pg_data_helpers.py" "$SERVER:$PROJECT/backend/app/services/"
scp "$LOCAL/backend/app/routers/sessions.py" "$LOCAL/backend/app/routers/coach.py" "$SERVER:$PROJECT/backend/app/routers/"
scp "$LOCAL/backend/migrations/102_classroom_lived_wisdom.sql" "$SERVER:$PROJECT/backend/migrations/"
```

## 2. Run migration 102 on server

```bash
ssh root@68.183.168.75 "docker exec nate_postgres psql -U nate_admin -d little_nate -f -" < backend/migrations/102_classroom_lived_wisdom.sql
# Or from on the server:
# docker exec -i nate_postgres psql -U nate_admin -d little_nate < /opt/clinical-sovereignty-lab/backend/migrations/102_classroom_lived_wisdom.sql
```

## 3. Restart backend and bridge (use docker-compose.prod.yml)

```bash
ssh root@68.183.168.75 "cd /opt/clinical-sovereignty-lab && docker compose -f docker-compose.prod.yml restart backend bridge"
```

## 4. Flutter web build → deploy (no --delete)

```bash
# From project root, after: cd mobile && flutter build web --release
rsync -avz mobile/build/web/ root@68.183.168.75:/var/www/sovereignsanctuary-web/
rsync -avz mobile/build/web/ root@68.183.168.75:/var/www/coach-portal/
```

## 5. Verify (per build-deploy-ux-verification.mdc)

- `curl -s http://localhost:8000/health` → `{"status": "healthy"}`
- `GET /api/coach/classroom/analyses/{coach_id}` returns `{"analyses": [...]}` (or `[]` if no data yet)
- Bridge logs: no `load_sessions` NameError; CLASSROOM tab loads sessions from PG

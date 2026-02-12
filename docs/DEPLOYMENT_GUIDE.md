# Little Nate — Deployment Guide

## Version 1.0 | January 21, 2026

---

## 📦 Prerequisites

- Docker 20.10+
- Docker Compose 2.0+
- 4GB+ RAM
- 20GB+ disk space
- SSL certificate (for production)

---

## 🚀 Quick Start

### 1. Clone and Configure

```bash
# Clone repository
git clone https://github.com/your-org/little-nate.git
cd little-nate

# Create environment file
cp .env.template .env
chmod 600 .env

# Edit with your values
nano .env
```

### 2. Generate Secrets

```bash
# Generate JWT secret
echo "JWT_SECRET=$(openssl rand -hex 64)" >> .env

# Generate database password
echo "DB_PASSWORD=$(openssl rand -base64 32)" >> .env

# Generate Redis password
echo "REDIS_PASSWORD=$(openssl rand -base64 32)" >> .env
```

### 3. SSL Certificates

For production, place your certificates in `./nginx/ssl/`:

```bash
mkdir -p nginx/ssl
cp /path/to/fullchain.pem nginx/ssl/
cp /path/to/privkey.pem nginx/ssl/
chmod 600 nginx/ssl/*.pem
```

For development, generate self-signed:

```bash
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout nginx/ssl/privkey.pem \
  -out nginx/ssl/fullchain.pem \
  -subj "/CN=localhost"
```

### 4. Build and Launch

```bash
# Build images
docker-compose build

# Start services
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f
```

### 5. Initialize Database

```bash
# Run migrations (first time only)
docker-compose exec api python migrate_to_postgres.py
```

### 6. Verify Deployment

```bash
# Health check
curl http://localhost:8000/health

# API docs
open http://localhost:8000/api/docs

# Admin console
open http://localhost:3000
```

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         NGINX                                │
│              (Reverse Proxy + SSL Termination)               │
│                    Ports: 80, 443                            │
└───────────────┬───────────────┬───────────────┬─────────────┘
                │               │               │
        ┌───────▼───────┐ ┌─────▼─────┐ ┌───────▼───────┐
        │   API Server  │ │  Bridge   │ │ Admin Console │
        │   (FastAPI)   │ │ (WebSocket)│ │   (Static)   │
        │   Port: 8000  │ │ Port: 8765│ │   Port: 3000  │
        └───────┬───────┘ └─────┬─────┘ └───────────────┘
                │               │
        ┌───────▼───────────────▼───────┐
        │         PostgreSQL            │
        │          Port: 5432           │
        └───────────────┬───────────────┘
                        │
        ┌───────────────▼───────────────┐
        │            Redis              │
        │          Port: 6379           │
        └───────────────────────────────┘
```

---

## 📁 Directory Structure

```
little-nate/
├── docker-compose.yml
├── Dockerfile.api
├── Dockerfile.bridge
├── .env
├── .env.template
├── nginx/
│   ├── nginx.conf
│   └── ssl/
│       ├── fullchain.pem
│       └── privkey.pem
├── Vaults/
│   ├── Admin/
│   │   └── night_school/
│   ├── Coaches/
│   └── Clients/
├── logs/
│   └── nginx/
├── admin_build/          # React build output
│   └── index.html
└── src/
    ├── api_server.py
    ├── bridge_server_hybrid.py
    ├── nevedal_engine.py
    ├── night_school_director.py
    └── ...
```

---

## 🔧 Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DB_PASSWORD` | Yes | PostgreSQL password |
| `REDIS_PASSWORD` | Yes | Redis password |
| `JWT_SECRET` | Yes | 256-bit secret for tokens |
| `AZURE_API_KEY` | Yes | Azure OpenAI API key |
| `AZURE_OPENAI_ENDPOINT` | Yes | Azure realtime endpoint |

### Scaling

```bash
# Scale API servers
docker-compose up -d --scale api=3

# Scale bridge servers (requires sticky sessions)
docker-compose up -d --scale bridge=2
```

---

## 🔒 Security Checklist

- [ ] Change all default passwords in `.env`
- [ ] Use real SSL certificates (not self-signed)
- [ ] Enable firewall (only expose 80, 443)
- [ ] Set up regular database backups
- [ ] Configure log rotation
- [ ] Enable audit logging
- [ ] Review rate limits
- [ ] Set up monitoring/alerting

---

## 📊 Monitoring

### Health Checks

```bash
# All services
docker-compose ps

# API health
curl http://localhost:8000/health

# Database
docker-compose exec postgres pg_isready -U littlenate

# Redis
docker-compose exec redis redis-cli ping
```

### Logs

```bash
# All logs
docker-compose logs -f

# Specific service
docker-compose logs -f api

# Nginx access logs
tail -f logs/nginx/access.log
```

### Metrics

```bash
# Container stats
docker stats

# Database connections
docker-compose exec postgres psql -U littlenate -c "SELECT count(*) FROM pg_stat_activity;"
```

---

## 🔄 Updates

### Code Updates

```bash
# Pull latest code
git pull

# Rebuild and restart
docker-compose build
docker-compose up -d

# Run migrations if needed
docker-compose exec api python migrate_to_postgres.py
```

### Database Migrations

```bash
# Backup first
docker-compose exec postgres pg_dump -U littlenate little_nate > backup.sql

# Run migration
docker-compose exec api python migrate_to_postgres.py

# Verify
docker-compose exec postgres psql -U littlenate -c "\dt"
```

---

## 🚨 Troubleshooting

### Container Won't Start

```bash
# Check logs
docker-compose logs api

# Check health
docker-compose ps

# Restart
docker-compose restart api
```

### Database Connection Issues

```bash
# Verify postgres is running
docker-compose exec postgres pg_isready

# Check connection string
docker-compose exec api env | grep DATABASE_URL

# Test connection
docker-compose exec api python -c "import asyncpg; print('OK')"
```

### WebSocket Issues

```bash
# Check bridge logs
docker-compose logs bridge

# Test WebSocket
wscat -c ws://localhost:8765

# Check nginx upgrade headers
curl -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" \
  http://localhost/ws
```

### SSL Issues

```bash
# Verify certificates
openssl x509 -in nginx/ssl/fullchain.pem -text -noout

# Test SSL
openssl s_client -connect localhost:443
```

---

## 💾 Backup & Restore

### Database Backup

```bash
# Full backup
docker-compose exec postgres pg_dump -U littlenate little_nate > backup_$(date +%Y%m%d).sql

# Compressed
docker-compose exec postgres pg_dump -U littlenate little_nate | gzip > backup_$(date +%Y%m%d).sql.gz
```

### Database Restore

```bash
# Stop services
docker-compose stop api bridge

# Restore
docker-compose exec -T postgres psql -U littlenate little_nate < backup.sql

# Restart
docker-compose start api bridge
```

### Vault Backup

```bash
# Backup Vaults directory
tar -czvf vaults_backup_$(date +%Y%m%d).tar.gz Vaults/
```

---

## 📞 Support

- **Documentation:** https://docs.littlenate.ai
- **Issues:** https://github.com/your-org/little-nate/issues
- **Security:** security@littlenate.ai

---

*Little Nate Platform — Deployment Guide v1.0*


1. First, copy all updated code from your Mac
On your Mac terminal:
# Copy entire backend folder (includes sessions.py with Zoom endpoints + night_school files)scp -r /Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2/backend/app \  root@68.183.168.75:/opt/clinical-sovereignty-lab/backend/
2. On the droplet: Update CORS and rebuild
# SSH to dropletssh root@68.183.168.75# Update CORS in .envcd /opt/clinical-sovereignty-labsed -i 's|^CORS_ORIGINS=.*|CORS_ORIGINS=http://localhost:3000,https://app.sovereignsanctuary.net,https://api.sovereignsanctuary.net|' .env# Verify it tookgrep CORS_ORIGINS .env# Rebuild BOTH containers (code is baked in)docker compose -f docker-compose.prod.yml build backend bridge# Restart bothdocker compose -f docker-compose.prod.yml up -d backend bridge# Verify healthydocker compose -f docker-compose.prod.yml ps# Check backend logs for startupdocker compose -f docker-compose.prod.yml logs --tail=30 backend
3. Test
Hard refresh https://app.sovereignsanctuary.net (Cmd+Shift+R), then:
Schedule tab → Zoom delete/archive should work (no CORS, no 404)
Dojo → Start Session should work (Night School modules now included)

## copy backend code
scp -r /Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2/backend/app root@68.183.168.75:/opt/clinical-sovereignty-lab/backend/



## best rebuild so far
cd /opt/clinical-sovereignty-lab && docker compose -f docker-compose.prod.yml build backend bridge && docker compose -f docker-compose.prod.yml up -d backend bridge

## best rebuild no cache
cd /opt/clinical-sovereignty-lab && docker compose -f docker-compose.prod.yml build --no-cache backend bridge && docker compose -f docker-compose.prod.yml up -d backend bridge


Page    URL
Login    https://app.sovereignsanctuary.net/index.html
Night School    https://app.sovereignsanctuary.net/night_school.html
Night School Dojo    https://app.sovereignsanctuary.net/night_school_dojo.html
Ask Nate    https://app.sovereignsanctuary.net/ask_nate.html
The Eye    https://app.sovereignsanctuary.net/the_eye.html
Crisis Center    https://app.sovereignsanctuary.net/crisis_center.html
Coach Approvals    https://app.sovereignsanctuary.net/coach_approvals.html
My Clients    https://app.sovereignsanctuary.net/my_clients.html
Nevedal Lab    https://app.sovereignsanctuary.net/nevedal_lab_live.html
Users    https://app.sovereignsanctuary.net/users.html


rsync -avz /Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2/mobile/build/web/ root@68.183.168.75:/var/www/sovereignsanctuary-web/

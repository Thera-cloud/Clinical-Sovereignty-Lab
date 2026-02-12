#!/bin/bash
# ==============================================
# Deployment Script - Coach-Only Clients & Matching
# Server: 68.183.168.75
# ==============================================
set -e

SERVER="root@68.183.168.75"
PROJECT="/opt/clinical-sovereignty-lab"
LOCAL="/Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2"

echo "=============================================="
echo "  Little Nate Deployment - Coach-Only Update"
echo "=============================================="
echo ""

# Step 1: Add SSH key to agent (you'll enter passphrase once)
echo "[1/7] Adding SSH key to agent..."
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519
echo ""

# Step 2: Deploy backend services
echo "[2/7] Deploying backend services..."
scp "$LOCAL/backend/app/services/night_school_director.py" \
    "$LOCAL/backend/app/services/coach_matcher.py" \
    "$LOCAL/backend/app/services/classroom_analyzer.py" \
    "$LOCAL/backend/app/services/search_proxy.py" \
    "$SERVER:$PROJECT/backend/app/services/"
echo "  ✓ night_school_director.py"
echo "  ✓ coach_matcher.py"
echo "  ✓ classroom_analyzer.py"
echo "  ✓ search_proxy.py (NEW - secure internet search)"
echo ""

# Step 3: Deploy backend websocket handlers
echo "[3/7] Deploying WebSocket handlers..."
scp "$LOCAL/backend/app/websocket/bridge_server.py" \
    "$LOCAL/backend/app/websocket/notification_system.py" \
    "$LOCAL/backend/app/websocket/night_school_handlers.py" \
    "$SERVER:$PROJECT/backend/app/websocket/"
echo "  ✓ bridge_server.py"
echo "  ✓ notification_system.py"
echo "  ✓ night_school_handlers.py"
echo ""

# Step 4: Deploy backend routers + main + requirements
echo "[4/7] Deploying routers, main.py, and requirements..."
scp "$LOCAL/backend/app/routers/dojo_api.py" \
    "$LOCAL/backend/app/routers/sessions.py" \
    "$SERVER:$PROJECT/backend/app/routers/"
scp "$LOCAL/backend/app/main.py" \
    "$SERVER:$PROJECT/backend/app/"
scp "$LOCAL/backend/requirements.txt" \
    "$SERVER:$PROJECT/backend/"
echo "  ✓ dojo_api.py (NEW)"
echo "  ✓ sessions.py"
echo "  ✓ main.py"
echo "  ✓ requirements.txt"
echo ""

# Step 5: Deploy dashboard (to both source dir AND web root)
echo "[5/7] Deploying dashboard..."
scp "$LOCAL/dashboard/night_school_dojo.html" \
    "$LOCAL/dashboard/command.html" \
    "$LOCAL/dashboard/coach_approvals.html" \
    "$SERVER:$PROJECT/dashboard/"
scp "$LOCAL/dashboard/night_school_dojo.html" \
    "$LOCAL/dashboard/command.html" \
    "$LOCAL/dashboard/coach_approvals.html" \
    "$SERVER:/var/www/sovereignsanctuary-web/"
echo "  ✓ night_school_dojo.html → source dir + web root"
echo "  ✓ command.html → source dir + web root (admin search approvals)"
echo "  ✓ coach_approvals.html → source dir + web root (save error handling)"
echo ""

# Step 6: Deploy mobile source + web build
echo "[6/7] Deploying mobile source and web build..."
scp "$LOCAL/mobile/lib/main.dart" \
    "$LOCAL/mobile/lib/updated_screens.dart" \
    "$SERVER:$PROJECT/mobile/lib/"
scp "$LOCAL/mobile/lib/screens/settings_screen.dart" \
    "$SERVER:$PROJECT/mobile/lib/screens/"
scp "$LOCAL/mobile/pubspec.yaml" \
    "$SERVER:$PROJECT/mobile/"
echo "  ✓ main.dart"
echo "  ✓ updated_screens.dart"
echo "  ✓ settings_screen.dart"
echo "  ✓ pubspec.yaml"

# Copy dashboard HTML files into build/web BEFORE rsync (so --delete doesn't wipe them)
# IMPORTANT: Skip index.html to preserve Flutter's app bootstrap
echo "  Copying dashboard files into web build..."
for f in "$LOCAL/dashboard/"*.html; do
    fname=$(basename "$f")
    if [ "$fname" != "index.html" ]; then
        cp "$f" "$LOCAL/mobile/build/web/"
    fi
done

# Rsync web build (now includes dashboard HTML)
cd "$LOCAL/mobile"
# NOTE: Do NOT use --delete here. It will wipe server files not in local build.
rsync -avz build/web/ "$SERVER:/var/www/sovereignsanctuary-web/"
echo "  ✓ Web build synced"
echo ""

# Step 7: Rebuild bridge (for sendgrid), install deps, restart containers
echo "[7/7] Rebuilding bridge and restarting containers..."
ssh "$SERVER" << 'EOF'
cd /opt/clinical-sovereignty-lab

# Rebuild bridge so new requirements (sendgrid) are installed
echo "  Rebuilding bridge image (sendgrid, twilio)..."
docker compose -f docker-compose.prod.yml build bridge 2>/dev/null || true

# Install dependencies in the backend container
echo "  Installing fpdf2, pyotp, qrcode in backend..."
docker compose -f docker-compose.prod.yml exec -T backend pip install fpdf2==2.7.9 pyotp==2.9.0 qrcode==7.4.2 2>/dev/null || \
docker compose -f docker-compose.prod.yml exec -T nate_backend pip install fpdf2==2.7.9 pyotp==2.9.0 qrcode==7.4.2 2>/dev/null || \
echo "  Note: Will install via requirements.txt on rebuild"

# Create necessary directories
echo "  Creating directories..."
docker compose -f docker-compose.prod.yml exec -T backend mkdir -p /app/dojo_assessments /app/classroom_videos 2>/dev/null || \
docker compose -f docker-compose.prod.yml exec -T nate_backend mkdir -p /app/dojo_assessments /app/classroom_videos 2>/dev/null || true

# Recreate bridge with new image (sendgrid), restart backend
echo "  Recreating bridge, restarting backend..."
docker compose -f docker-compose.prod.yml up -d bridge 2>/dev/null || true
docker compose -f docker-compose.prod.yml restart backend 2>/dev/null || \
docker compose -f docker-compose.prod.yml restart nate_backend 2>/dev/null

# Check container status
echo ""
echo "  Container status:"
docker compose -f docker-compose.prod.yml ps

# Check logs for errors
echo ""
echo "  Recent backend logs:"
docker compose -f docker-compose.prod.yml logs --tail=15 backend 2>/dev/null || \
docker compose -f docker-compose.prod.yml logs --tail=15 nate_backend 2>/dev/null
EOF

echo ""
echo "=============================================="
echo "  Deployment Complete!"
echo "=============================================="
echo ""
echo "Files deployed:"
echo "  Backend:   bridge_server.py, night_school_director.py,"
echo "             coach_matcher.py, classroom_analyzer.py,"
echo "             search_proxy.py (new), night_school_handlers.py,"
echo "             dojo_api.py, sessions.py, main.py, requirements.txt"
echo "  Dashboard: night_school_dojo.html, command.html"
echo "  Mobile:    main.dart, updated_screens.dart, pubspec.yaml"
echo "  Frontend:  Web build rsync'd"
echo ""
echo "New features deployed:"
echo "  • Coach-Only client registration & scheduling"
echo "  • Client-Coach matching system"
echo "  • Classroom video upload & coach query"
echo "  • Multi-domain DOJO (PM, Business, CNC, MCAT, Teacher)"
echo "  • PDF assessment generation (jsPDF client-side)"
echo "  • Client filter/search on Insights, Clients, Briefings"
echo "  • Secure Internet Search (3-layer: Coach→2FA→Admin→Results Review)"

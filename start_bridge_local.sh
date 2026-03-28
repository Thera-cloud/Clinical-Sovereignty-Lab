#!/bin/bash
cd ~/Desktop/Clinical-Sovereignty-Lab-2/backend

# Load .env FIRST for inference keys (NATE_CHAT_*, AZURE_*, WORKERS_AI_*, etc.)
if [ -f .env ]; then
  set -a && source .env && set +a
fi

# Override with local-dev values AFTER sourcing .env (these take priority)
export PYTHONPATH=.
export CLI_PROJECT_ROOT=~/Desktop/Clinical-Sovereignty-Lab-2
export JWT_SECRET="sovereign-sanctuary-dev-secret-key-minimum-32chars"
export DATA_DIR=app/websocket/data
export POSTGRES_PASSWORD="localdev"
export ADMIN_USERNAME="DrNevedal1"
export ADMIN_PASSWORD="localdev123"
# Skip Redis cache sync when Redis isn't running (avoids "Connection refused" retries)
export SKIP_REDIS_CACHE_SYNC=1

# Crystal sync: push BLUE crystals to production via REST API
export PRODUCTION_API_URL="https://api.sovereignsanctuary.net"
# Set SKYEYE_AUDIT_TOKEN in .env (get from server: grep SKYEYE_AUDIT_TOKEN /opt/clinical-sovereignty-lab/.env)

while true; do
  python3.11 app/websocket/bridge_server.py
  echo ""
  echo ">>> Bridge exited (code $?). Restarting in 5s..."
  read -r || break
done

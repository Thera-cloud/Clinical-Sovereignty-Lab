#!/usr/bin/env bash
# Deploy the ORANGE Voice Emotion Server (wav2vec2) to Hetzner CAX41.
#
# Per .cursor/rules/three-node-sync-discipline.mdc:
#   - ORANGE is reachable via WireGuard from GREEN at 10.13.13.5
#   - From BLUE (this Mac), use SSH ProxyJump through GREEN
#
# Run from BLUE:
#     cd backend/scripts/orange
#     ./deploy.sh
#
# Idempotent: safe to re-run after editing voice_emotion_server.py.
#
# Required env (or override on the command line):
#   GREEN_HOST    SSH target for the DigitalOcean VPS (jump host)
#   ORANGE_HOST   SSH target for ORANGE over WireGuard
#   BEARER_FILE   Path on BLUE to the shared bearer token (one line, no \n)

set -euo pipefail

GREEN_HOST="${GREEN_HOST:-root@68.183.168.75}"
ORANGE_HOST="${ORANGE_HOST:-root@10.13.13.5}"
ORANGE_REMOTE_DIR="${ORANGE_REMOTE_DIR:-/opt/sovereign/voice-emotion}"
ORANGE_VENV="${ORANGE_VENV:-/opt/sovereign/voice-emotion/.venv}"
ORANGE_ENV_FILE="${ORANGE_ENV_FILE:-/etc/sovereign/voice_emotion.env}"
SERVICE_FILE="/etc/systemd/system/voice_emotion_server.service"
BEARER_FILE="${BEARER_FILE:-$HOME/.sovereign/classroom_remote_bearer.txt}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANALYZER_SRC="$SCRIPT_DIR/../../app/services/voice_emotion_analyzer.py"

if [ ! -f "$BEARER_FILE" ]; then
    echo "ERROR: bearer file $BEARER_FILE not found." >&2
    echo "       Generate with: openssl rand -hex 32 > $BEARER_FILE && chmod 600 $BEARER_FILE" >&2
    exit 1
fi
if [ ! -f "$ANALYZER_SRC" ]; then
    echo "ERROR: $ANALYZER_SRC missing — repo layout mismatch." >&2
    exit 1
fi

BEARER="$(tr -d '\n' < "$BEARER_FILE")"
if [ -z "$BEARER" ]; then
    echo "ERROR: bearer file is empty." >&2
    exit 1
fi

echo "==> [1/6] Ensuring remote directory on ORANGE: $ORANGE_REMOTE_DIR"
ssh -J "$GREEN_HOST" "$ORANGE_HOST" "mkdir -p '$ORANGE_REMOTE_DIR' /etc/sovereign"

echo "==> [2/6] Pushing voice_emotion_server.py + analyzer + systemd unit"
scp -o ProxyJump="$GREEN_HOST" \
    "$SCRIPT_DIR/voice_emotion_server.py" \
    "$ORANGE_HOST:$ORANGE_REMOTE_DIR/voice_emotion_server.py"
scp -o ProxyJump="$GREEN_HOST" \
    "$ANALYZER_SRC" \
    "$ORANGE_HOST:$ORANGE_REMOTE_DIR/voice_emotion_analyzer.py"
scp -o ProxyJump="$GREEN_HOST" \
    "$SCRIPT_DIR/voice_emotion_server.service" \
    "$ORANGE_HOST:$SERVICE_FILE"

echo "==> [3/6] Writing bearer env file at $ORANGE_ENV_FILE (mode 600)"
ssh -J "$GREEN_HOST" "$ORANGE_HOST" \
    "umask 077 && printf 'CLASSROOM_REMOTE_AUTH_TOKEN=%s\n' '$BEARER' > '$ORANGE_ENV_FILE' && chmod 600 '$ORANGE_ENV_FILE'"

echo "==> [4/6] Verifying / creating venv with wav2vec2 deps (first run is slow)"
ssh -J "$GREEN_HOST" "$ORANGE_HOST" "bash -s" <<EOF
set -euo pipefail
if ! command -v ffmpeg >/dev/null 2>&1; then
    apt-get update && apt-get install -y --no-install-recommends ffmpeg python3-venv
fi
if [ ! -d "$ORANGE_VENV" ]; then
    python3 -m venv "$ORANGE_VENV"
fi
"$ORANGE_VENV/bin/pip" install --upgrade --quiet pip wheel
"$ORANGE_VENV/bin/pip" install --quiet \
    fastapi 'uvicorn[standard]' httpx pydantic \
    librosa numpy soundfile \
    torch torchaudio transformers
echo "venv ready: $($ORANGE_VENV/bin/python --version)"
EOF

echo "==> [5/6] Updating systemd unit paths + reloading + starting"
ssh -J "$GREEN_HOST" "$ORANGE_HOST" "bash -s" <<EOF
set -euo pipefail
# Patch the service file in-place so it points at the venv we just created
# and the directory we vendored to (avoids the /opt/sandbox path that the
# original template assumed).
sed -i \
    -e "s|^WorkingDirectory=.*|WorkingDirectory=$ORANGE_REMOTE_DIR|" \
    -e "s|^ExecStart=.*|ExecStart=$ORANGE_VENV/bin/uvicorn voice_emotion_server:app --host 0.0.0.0 --port 8090 --log-level info --timeout-keep-alive 1800|" \
    "$SERVICE_FILE"
# Some hosts don't have a 'sandbox' user — fall back to root if missing.
if ! id sandbox >/dev/null 2>&1; then
    sed -i -e "s|^User=.*|User=root|" -e "s|^Group=.*|Group=root|" "$SERVICE_FILE"
fi
systemctl daemon-reload
systemctl enable voice_emotion_server.service
systemctl restart voice_emotion_server.service
sleep 4
systemctl --no-pager --full status voice_emotion_server.service | tail -25 || true
EOF

echo "==> [6/6] Probing /health from GREEN over WireGuard (auth-aware)"
ssh "$GREEN_HOST" "curl -sf --max-time 15 http://10.13.13.5:8090/health" | python3 -m json.tool

cat <<EOF

ORANGE voice-emotion server is live at http://10.13.13.5:8090

Files on ORANGE:
  $ORANGE_REMOTE_DIR/voice_emotion_server.py
  $ORANGE_REMOTE_DIR/voice_emotion_analyzer.py
  $ORANGE_VENV/
  $ORANGE_ENV_FILE   (CLASSROOM_REMOTE_AUTH_TOKEN, mode 600)
  $SERVICE_FILE
EOF

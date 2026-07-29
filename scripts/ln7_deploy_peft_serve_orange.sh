#!/usr/bin/env bash
# Deploy LN7 PEFT serve to ORANGE via ProxyJump — sync full adapter tree from BLUE.
#   bash scripts/ln7_deploy_peft_serve_orange.sh [adapter_dirname]
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
ADAPTER_NAME="${1:-LN7-2026-07-28T054420Z}"
GREEN="${LN7_GREEN_HOST:-root@68.183.168.75}"
ORANGE_IP="${LN7_ORANGE_WG:-10.13.13.5}"
SRC="$REPO/.ln7-adapters/${ADAPTER_NAME}"

if [[ ! -d "$SRC" ]]; then
  echo "[peft] FAIL: missing BLUE adapter dir $SRC" >&2
  exit 2
fi

echo "[peft] deploy adapter=$ADAPTER_NAME → $ORANGE_IP:11435"
scp -o BatchMode=yes -o ProxyJump="$GREEN" \
  "$REPO/backend/scripts/orange/ln7_peft_server.py" \
  "root@${ORANGE_IP}:/opt/ln7/peft_serve/ln7_peft_server.py"

# Full adapter tree BLUE → ORANGE (overwrite)
ssh -o BatchMode=yes -o ProxyJump="$GREEN" "root@${ORANGE_IP}" \
  "mkdir -p /opt/ln7/adapters/${ADAPTER_NAME}"
scp -o BatchMode=yes -o ProxyJump="$GREEN" -r "$SRC/." \
  "root@${ORANGE_IP}:/opt/ln7/adapters/${ADAPTER_NAME}/"

# Restore PEFT adapter_config from checkpoint if root was clobbered
if [[ -f "$SRC/checkpoint-40/adapter_config.json" ]]; then
  scp -o BatchMode=yes -o ProxyJump="$GREEN" \
    "$SRC/checkpoint-40/adapter_config.json" \
    "root@${ORANGE_IP}:/opt/ln7/adapters/${ADAPTER_NAME}/adapter_config.json"
fi

ssh -o BatchMode=yes -o ProxyJump="$GREEN" "root@${ORANGE_IP}" \
  "ADAPTER_NAME='$ADAPTER_NAME' bash -s" <<'REMOTE'
set -euo pipefail
mkdir -p /opt/ln7/peft_serve /opt/ln7/hf_cache
test -d "/opt/ln7/adapters/$ADAPTER_NAME"
cat > /etc/systemd/system/ln7_peft_server.service <<UNIT
[Unit]
Description=LN7 PEFT OpenAI-compat server (WireGuard :11435)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/ln7/peft_serve
Environment=LN7_ADAPTER_DIR=/opt/ln7/adapters/${ADAPTER_NAME}
Environment=LN7_QLORA_HF_BASE=Qwen/Qwen2.5-Coder-1.5B-Instruct
Environment=LN7_PEFT_MODEL_ID=ln7-peft
Environment=LN7_PEFT_HOST=10.13.13.5
Environment=LN7_PEFT_PORT=11435
Environment=HF_HOME=/opt/ln7/hf_cache
Environment=PATH=/opt/ln7/peft_serve/.venv/bin:/usr/local/bin:/usr/bin
ExecStart=/opt/ln7/peft_serve/.venv/bin/python /opt/ln7/peft_serve/ln7_peft_server.py
Restart=on-failure
RestartSec=8
MemoryMax=12G

[Install]
WantedBy=multi-user.target
UNIT
ufw allow from 10.13.13.0/24 to any port 11435 proto tcp comment 'LN7 PEFT WG' || true
cd /opt/ln7/peft_serve
[[ -d .venv ]] || python3 -m venv .venv
. .venv/bin/activate
# Skip pip when peft already importable
if ! python -c 'import peft, fastapi, transformers' 2>/dev/null; then
  pip install -q --upgrade pip
  pip install -q torch --index-url https://download.pytorch.org/whl/cpu
  pip install -q 'fastapi>=0.110' uvicorn pydantic transformers peft accelerate safetensors sentencepiece
fi
systemctl daemon-reload
systemctl enable ln7_peft_server
systemctl restart ln7_peft_server
echo "[peft] remote restart issued for $ADAPTER_NAME"
REMOTE

# Health from GREEN→WG (ORANGE self-curl to 10.13.13.5 can stall/buffer; localhost not bound)
ok=0
for i in $(seq 1 60); do
  h="$(ssh -o BatchMode=yes -o ConnectTimeout=20 "$GREEN" \
    "curl -sS --max-time 5 http://${ORANGE_IP}:11435/health 2>/dev/null || true")"
  echo "[peft] health_try_$i $h"
  if echo "$h" | grep -qE '"loaded"[[:space:]]*:[[:space:]]*true'; then
    if echo "$h" | grep -q "$ADAPTER_NAME"; then
      ok=1
      break
    fi
    echo "[peft] WARN: loaded but adapter_dir may not match $ADAPTER_NAME"
    ok=1
    break
  fi
  sleep 8
done
[[ "$ok" == "1" ]] || { echo "[peft] FAIL: health never loaded $ADAPTER_NAME" >&2; exit 3; }
echo "[peft] done adapter=$ADAPTER_NAME"

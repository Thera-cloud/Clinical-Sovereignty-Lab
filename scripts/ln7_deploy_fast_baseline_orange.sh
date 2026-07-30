#!/usr/bin/env bash
# Deploy bare Qwen2.5-Coder-7B PEFT serve as LN7-fast-baseline (no LoRA).
#   bash scripts/ln7_deploy_fast_baseline_orange.sh
#
# # QUANTUM-CRYSTAL-ARCH
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
GREEN="${LN7_GREEN_HOST:-root@68.183.168.75}"
ORANGE_IP="${LN7_ORANGE_WG:-10.13.13.5}"
HF_BASE="${LN7_QLORA_HF_BASE:-Qwen/Qwen2.5-Coder-7B-Instruct}"
REV="${LN7_FAST_BASELINE_ID:-LN7-fast-baseline}"

echo "[fast-baseline] deploy bare $HF_BASE as $REV → ${ORANGE_IP}:11435"
scp -o BatchMode=yes -o ProxyJump="$GREEN" \
  "$REPO/backend/scripts/orange/ln7_peft_server.py" \
  "root@${ORANGE_IP}:/opt/ln7/peft_serve/ln7_peft_server.py"

ssh -o BatchMode=yes -o ProxyJump="$GREEN" "root@${ORANGE_IP}" \
  "HF_BASE='$HF_BASE' REV='$REV' bash -s" <<'REMOTE'
set -euo pipefail
mkdir -p /opt/ln7/peft_serve /opt/ln7/hf_cache "/opt/ln7/adapters/${REV}"
echo "bare_baseline=1" >"/opt/ln7/adapters/${REV}/BASELINE.txt"
cat > /etc/systemd/system/ln7_peft_server.service <<UNIT
[Unit]
Description=LN7 PEFT OpenAI-compat server (WireGuard :11435)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/ln7/peft_serve
Environment=LN7_ADAPTER_DIR=/opt/ln7/adapters/${REV}
Environment=LN7_QLORA_HF_BASE=${HF_BASE}
Environment=LN7_PEFT_MODEL_ID=ln7-peft
Environment=LN7_PEFT_HOST=10.13.13.5
Environment=LN7_PEFT_PORT=11435
Environment=LN7_PEFT_BARE=1
Environment=LN7_PEFT_REVISION_ID=${REV}
Environment=HF_HOME=/opt/ln7/hf_cache
Environment=PATH=/opt/ln7/peft_serve/.venv/bin:/usr/local/bin:/usr/bin
ExecStart=/opt/ln7/peft_serve/.venv/bin/python /opt/ln7/peft_serve/ln7_peft_server.py
Restart=on-failure
RestartSec=8
MemoryMax=28G

[Install]
WantedBy=multi-user.target
UNIT
ufw allow from 10.13.13.0/24 to any port 11435 proto tcp comment 'LN7 PEFT WG' || true
cd /opt/ln7/peft_serve
[[ -d .venv ]] || python3 -m venv .venv
. .venv/bin/activate
if ! python -c 'import peft, fastapi, transformers' 2>/dev/null; then
  pip install -q --upgrade pip
  pip install -q torch --index-url https://download.pytorch.org/whl/cpu
  pip install -q 'fastapi>=0.110' uvicorn pydantic transformers peft accelerate safetensors sentencepiece
fi
systemctl daemon-reload
systemctl enable ln7_peft_server
systemctl restart ln7_peft_server
echo "[fast-baseline] remote restart issued bare=$HF_BASE rev=$REV"
REMOTE

ok=0
for i in $(seq 1 90); do
  h="$(ssh -o BatchMode=yes -o ConnectTimeout=20 "$GREEN" \
    "curl -sS --max-time 8 http://${ORANGE_IP}:11435/health 2>/dev/null || true")"
  echo "[fast-baseline] health_try_$i $h"
  if echo "$h" | grep -qE '"loaded"[[:space:]]*:[[:space:]]*true'; then
    ok=1
    break
  fi
  sleep 10
done
[[ "$ok" == "1" ]] || { echo "[fast-baseline] FAIL: health never loaded" >&2; exit 3; }
echo "[fast-baseline] done $REV"

#!/usr/bin/env bash
# Register LN7-fast-baseline on GREEN (shadow/active-fast incumbent).
#   bash scripts/ln7_register_fast_baseline.sh
#
# # QUANTUM-CRYSTAL-ARCH
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
GREEN="${LN7_GREEN_HOST:-root@68.183.168.75}"
REV="${LN7_FAST_BASELINE_ID:-LN7-fast-baseline}"
HF="${LN7_QLORA_HF_BASE:-Qwen/Qwen2.5-Coder-7B-Instruct}"
PEFT_URL="${LN7_PEFT_URL:-http://10.13.13.5:11435}"

mkdir -p "$REPO/docs/ln7"
CARD="$REPO/docs/ln7/LN7_${REV}.md"
cat >"$CARD" <<EOF
# Little Nate 7 — ${REV}

| Field | Value |
|---|---|
| Revision | \`${REV}\` |
| Tier | fast |
| HF base | \`${HF}\` |
| Quantization | bare_hf (no LoRA) |
| PEFT URL | \`${PEFT_URL}\` |
| Role | Fast-tier incumbent for promote gate |

CEO activate of LoRA candidates must clear CI against this revision, not \`LN7-baseline\` (32B deep).
EOF

ssh -o BatchMode=yes "$GREEN" "python3 -" <<PY
import json, re, urllib.request
env = open("/opt/clinical-sovereignty-lab/.env").read()
tok = re.search(r"^SKYEYE_AUDIT_TOKEN=(.*)$", env, re.M).group(1).strip()
body = {
    "revision_id": "$REV",
    "base_checkpoint": "$HF",
    "quantization": "bare_hf",
    "status": "shadow",
    "notes": "Milestone A fast-tier incumbent — bare 7B PEFT serve; promote LoRA vs this id",
    "harness_config": {
        "tier": "fast",
        "force_peft": True,
        "peft_url": "$PEFT_URL",
        "peft_model": "ln7-peft",
        "hf_base": "$HF",
        "method": "bare_hf",
        "incumbent_role": True,
    },
    "scorecard": {"role": "fast_baseline", "activate": False},
}
req = urllib.request.Request(
    "http://localhost:8000/api/ln7/revision/register",
    data=json.dumps(body).encode(),
    headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=60) as r:
    print(r.read().decode())
PY
echo "[register] $REV card=$CARD"

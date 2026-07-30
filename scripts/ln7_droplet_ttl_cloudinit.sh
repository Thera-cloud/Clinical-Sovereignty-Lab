#!/usr/bin/env bash
# Emit cloud-init user-data that installs a droplet-side TTL self-destruct.
# The droplet carries its own death: after LN7_GPU_HARD_MAX_S (default 8h) it
# DELETEs itself via the DO API. Shutdown-only is insufficient (powered-off
# droplets still bill) — API delete is preferred; orchestrator orphan-reaper
# remains the third strap.
#
# Usage:
#   USERDATA="$(bash scripts/ln7_droplet_ttl_cloudinit.sh)"
#   doctl compute droplet create ... --user-data "$USERDATA"
#
# Token: prefer LN7_DROPLET_SELF_DELETE_TOKEN (delete-scoped). Fallback:
# DIGITALOCEAN_ACCESS_TOKEN | DO_TOKEN | doctl auth token.
#
# SECURITY: stdout IS the cloud-init document and embeds the token. Never tee
# this script's stdout to chat/logs/CI. Pipe only into doctl --user-data.
#
# # QUANTUM-CRYSTAL-ARCH
set -euo pipefail

TTL_S="${LN7_GPU_HARD_MAX_S:-${LN7_DROPLET_TTL_S:-28800}}"
if [[ "$TTL_S" -lt 900 ]]; then
  TTL_S=900
fi

resolve_token() {
  if [[ -n "${LN7_DROPLET_SELF_DELETE_TOKEN:-}" ]]; then echo "$LN7_DROPLET_SELF_DELETE_TOKEN"; return 0; fi
  if [[ -n "${DIGITALOCEAN_ACCESS_TOKEN:-}" ]]; then echo "$DIGITALOCEAN_ACCESS_TOKEN"; return 0; fi
  if [[ -n "${DO_TOKEN:-}" ]]; then echo "$DO_TOKEN"; return 0; fi
  if command -v doctl >/dev/null 2>&1; then
    doctl auth token 2>/dev/null | tr -d '[:space:]' || true
    return 0
  fi
  echo ""
}

TOKEN="$(resolve_token)"
if [[ -z "$TOKEN" ]]; then
  echo "[ln7-ttl-cloudinit] WARN: no DO token — timer will poweroff only (still bills)" >&2
fi

TTL_S="$TTL_S" TOKEN="$TOKEN" python3 - <<'PY'
import os, textwrap, json, base64
ttl = int(os.environ["TTL_S"])
token = os.environ.get("TOKEN", "")
script = textwrap.dedent(f"""\
#!/bin/bash
set -euo pipefail
TTL={ttl}
TOKEN={json.dumps(token)}
LOG=/var/log/ln7_ttl_self_destruct.log
ts() {{ date -u +%Y-%m-%dT%H%M%SZ; }}
echo "$(ts) sleep TTL=${{TTL}}s" >>"$LOG"
sleep "$TTL"
ID="$(curl -fsS --max-time 10 http://169.254.169.254/metadata/v1/id 2>/dev/null || true)"
echo "$(ts) droplet_id=${{ID:-unknown}}" >>"$LOG"
if [[ -n "$TOKEN" && -n "$ID" ]]; then
  for attempt in 1 2 3; do
    code="$(curl -sS -o /tmp/ln7_do_del.body -w '%{{http_code}}' --max-time 30 \\
      -X DELETE \\
      -H "Authorization: Bearer ${{TOKEN}}" \\
      -H "Content-Type: application/json" \\
      "https://api.digitalocean.com/v2/droplets/${{ID}}" || echo 000)"
    echo "$(ts) DELETE attempt=$attempt http=$code" >>"$LOG"
    if [[ "$code" == "204" || "$code" == "404" ]]; then
      echo "$(ts) self-delete ok" >>"$LOG"
      exit 0
    fi
    sleep 15
  done
  echo "$(ts) ALARM: API self-delete failed — powering off (still bills; orphan-reaper must catch)" >>"$LOG"
fi
shutdown -h now || poweroff || true
""")
b64 = base64.b64encode(script.encode()).decode()
unit_b64 = base64.b64encode(textwrap.dedent("""\
[Unit]
Description=LN7 droplet TTL self-destruct (API delete preferred)
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
ExecStart=/usr/local/bin/ln7_ttl_self_destruct.sh
Restart=no
[Install]
WantedBy=multi-user.target
""").encode()).decode()
print(f"""#cloud-config
# LN7 TTL self-destruct — droplet carries its own death
runcmd:
  - mkdir -p /usr/local/bin /etc/systemd/system
  - bash -c "echo {b64} | base64 -d > /usr/local/bin/ln7_ttl_self_destruct.sh"
  - chmod 700 /usr/local/bin/ln7_ttl_self_destruct.sh
  - bash -c "echo {unit_b64} | base64 -d > /etc/systemd/system/ln7-ttl-self-destruct.service"
  - systemctl daemon-reload
  - systemctl enable --now ln7-ttl-self-destruct.service
""")
PY

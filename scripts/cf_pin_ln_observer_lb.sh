#!/usr/bin/env bash
# Pin /api/ln-observer* to primary (ws-primary) on api.sovereignsanctuary.net LB.
# Requires Cloudflare API token with Account → Load Balancing → Edit.
# Usage (from repo root, with .env present):
#   bash scripts/cf_pin_ln_observer_lb.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
set -a
# Prefer non-interactive key extract (avoid sourcing broken .env lines)
get_kv() { grep -E "^$1=" "$ROOT/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d "\"'"; }
TOKEN="${CLOUDFLARE_LB_TOKEN:-$(get_kv CLOUDFLARE_LB_TOKEN)}"
TOKEN="${TOKEN:-$(get_kv CLOUDFLARE_API_TOKEN)}"
ACCT="${CLOUDFLARE_ACCOUNT_ID:-$(get_kv CLOUDFLARE_ACCOUNT_ID)}"
if [[ -z "${TOKEN}" || -z "${ACCT}" ]]; then
  echo "Missing CLOUDFLARE_LB_TOKEN (or CLOUDFLARE_API_TOKEN) / CLOUDFLARE_ACCOUNT_ID"
  exit 1
fi

NEW_COND='(starts_with(http.request.uri.path, "/ws") or starts_with(http.request.uri.path, "/api/ln-observer"))'

echo "Listing load balancers…"
LBS="$(curl -sS -H "Authorization: Bearer ${TOKEN}" \
  "https://api.cloudflare.com/client/v4/accounts/${ACCT}/load_balancers")"
echo "$LBS" | python3 -c "
import json,sys,os
d=json.load(sys.stdin)
if not d.get('success'):
    print('API error:', d.get('errors'))
    print('Create a token with Account.Load Balancing:Edit and set CLOUDFLARE_LB_TOKEN.')
    sys.exit(2)
lbs=d.get('result') or []
if not lbs:
    print('No load balancers on account'); sys.exit(3)
for lb in lbs:
    print(lb.get('id'), lb.get('name'), 'rules=', len(lb.get('rules') or []))
# Prefer hostname match
pick=None
for lb in lbs:
    name=(lb.get('name') or '')+(lb.get('description') or '')
    if 'api' in name.lower() or 'sovereign' in name.lower():
        pick=lb; break
pick=pick or lbs[0]
print('SELECTED', pick.get('id'), pick.get('name'))
open('/tmp/cf_lb_pick.json','w').write(json.dumps(pick))
"

LB_ID="$(python3 -c "import json; print(json.load(open('/tmp/cf_lb_pick.json'))['id'])")"
python3 <<PY
import json, copy, os, urllib.request
token=os.environ.get("TOKEN") or """${TOKEN}"""
acct="""${ACCT}"""
lb=json.load(open("/tmp/cf_lb_pick.json"))
new_cond="""${NEW_COND}"""
rules=copy.deepcopy(lb.get("rules") or [])
updated=False
for r in rules:
    name=(r.get("name") or "").lower()
    cond=r.get("condition") or ""
    if "websocket" in name or "/ws" in cond:
        r["condition"]=new_cond
        updated=True
        print("Updated rule:", r.get("name"), "->", new_cond)
        break
if not updated:
    # Append terminating override to ws-primary if present
    fb=lb.get("fallback_pool")
    rules.append({
        "name": "WebSocket + LN-Observer to Primary",
        "condition": new_cond,
        "terminates": True,
        "overrides": {
            "fallback_pool": fb,
            "session_affinity": "cookie",
        },
    })
    print("Appended new rule")
body={"rules": rules}
req=urllib.request.Request(
    f"https://api.cloudflare.com/client/v4/accounts/{acct}/load_balancers/{lb['id']}",
    data=json.dumps(body).encode(),
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    method="PATCH",
)
with urllib.request.urlopen(req, timeout=30) as resp:
    d=json.load(resp)
print("patch_ok", d.get("success"), d.get("errors"))
if not d.get("success"):
    raise SystemExit(4)
print("DONE — LN-Observer + /ws pinned via custom rule")
PY

#!/usr/bin/env bash
# Pin /api/ln-observer* + /ws to primary (ws-primary) on api.sovereignsanctuary.net LB.
# Requires Cloudflare API token with Account → Load Balancing Write (zone-scoped PUT).
# Prefer CLOUDFLARE_LB_TOKEN; falls back to CLOUDFLARE_API_TOKEN.
# Usage (from repo root, with .env present):
#   bash scripts/cf_pin_ln_observer_lb.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Never fail when a key is absent (set -e + pipefail + grep exit 1).
get_kv() { grep -E "^$1=" "$ROOT/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d "\"'" || true; }
TOKEN="${CLOUDFLARE_LB_TOKEN:-}"
TOKEN="${TOKEN:-$(get_kv CLOUDFLARE_LB_TOKEN)}"
TOKEN="${TOKEN:-$(get_kv CLOUDFLARE_API_TOKEN)}"
ACCT="${CLOUDFLARE_ACCOUNT_ID:-}"
ACCT="${ACCT:-$(get_kv CLOUDFLARE_ACCOUNT_ID)}"
ZONE="${CLOUDFLARE_ZONE_ID:-}"
ZONE="${ZONE:-$(get_kv CLOUDFLARE_ZONE_ID)}"
if [[ -z "${TOKEN}" || -z "${ACCT}" ]]; then
  echo "Missing CLOUDFLARE_LB_TOKEN (or CLOUDFLARE_API_TOKEN) / CLOUDFLARE_ACCOUNT_ID"
  exit 1
fi

NEW_COND='(starts_with(http.request.uri.path, "/ws") or starts_with(http.request.uri.path, "/api/ln-observer") or starts_with(http.request.uri.path, "/livekit"))'
export TOKEN ACCT ZONE NEW_COND

python3 <<'PY'
import copy, json, os, urllib.error, urllib.request

token = os.environ["TOKEN"]
acct = os.environ["ACCT"]
zone = os.environ.get("ZONE") or ""
new_cond = os.environ["NEW_COND"]

def api(method, url, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            d = json.loads(raw)
        except Exception:
            d = {"success": False, "errors": [{"message": raw[:300]}]}
        d["http"] = e.code
        return d

if not zone:
    z = api("GET", "https://api.cloudflare.com/client/v4/zones?name=sovereignsanctuary.net")
    if z.get("success") and z.get("result"):
        zone = z["result"][0]["id"]

print("Listing load balancers…")
lbs = None
if zone:
    lbs = api("GET", f"https://api.cloudflare.com/client/v4/zones/{zone}/load_balancers")
if not lbs or not lbs.get("success"):
    lbs = api("GET", f"https://api.cloudflare.com/client/v4/accounts/{acct}/load_balancers")
if not lbs.get("success"):
    print("API error:", lbs.get("errors"))
    print("Need Account Load Balancing Write (+ zone). Set CLOUDFLARE_LB_TOKEN.")
    raise SystemExit(2)

pick = None
for lb in lbs.get("result") or []:
    print(lb.get("id"), lb.get("name"), "rules=", len(lb.get("rules") or []))
    blob = ((lb.get("name") or "") + (lb.get("description") or "")).lower()
    if "api" in blob or "sovereign" in blob:
        pick = lb
pick = pick or (lbs.get("result") or [None])[0]
if not pick:
    print("No load balancers"); raise SystemExit(3)
print("SELECTED", pick.get("id"), pick.get("name"))

pools = api("GET", f"https://api.cloudflare.com/client/v4/accounts/{acct}/load_balancers/pools")
ws_primary = None
for p in pools.get("result") or []:
    if (p.get("name") or "").lower() == "ws-primary":
        ws_primary = p.get("id")

rules = copy.deepcopy(pick.get("rules") or [])
updated = False
for r in rules:
    name = (r.get("name") or "").lower()
    cond = r.get("condition") or ""
    if "websocket" in name or "/ws" in cond:
        print("Updated rule:", r.get("name"), "->", new_cond)
        r["condition"] = new_cond
        r["terminates"] = True
        ov = dict(r.get("overrides") or {})
        if ws_primary:
            ov["fallback_pool"] = ws_primary
        r["overrides"] = ov
        updated = True
        break
if not updated:
    rules.append({
        "name": "WebSocket + LN-Observer to Primary",
        "condition": new_cond,
        "terminates": True,
        "overrides": {
            "fallback_pool": ws_primary or pick.get("fallback_pool"),
            "session_affinity": "ip_cookie",
        },
    })
    print("Appended new rule")

put_body = {k: v for k, v in {
    "name": pick.get("name"),
    "fallback_pool": pick.get("fallback_pool"),
    "default_pools": pick.get("default_pools"),
    "proxied": pick.get("proxied", True),
    "ttl": pick.get("ttl"),
    "steering_policy": pick.get("steering_policy"),
    "session_affinity": pick.get("session_affinity"),
    "session_affinity_ttl": pick.get("session_affinity_ttl"),
    "session_affinity_attributes": pick.get("session_affinity_attributes"),
    "region_pools": pick.get("region_pools"),
    "country_pools": pick.get("country_pools"),
    "pop_pools": pick.get("pop_pools"),
    "rules": rules,
    "enabled": pick.get("enabled", True),
    "description": pick.get("description"),
}.items() if v is not None}

# Zone PUT is authoritative; account PATCH/PUT often returns Object not found.
if not zone:
    print("Missing CLOUDFLARE_ZONE_ID and zone lookup failed")
    raise SystemExit(4)
d = api("PUT", f"https://api.cloudflare.com/client/v4/zones/{zone}/load_balancers/{pick['id']}", put_body)
print("put_ok", d.get("success"), d.get("errors"))
if not d.get("success"):
    raise SystemExit(5)
for r in (d.get("result") or {}).get("rules") or []:
    print("AFTER", r.get("name"), "|", r.get("condition"))
print("DONE — LN-Observer + /ws pinned via custom rule (zone PUT)")
PY

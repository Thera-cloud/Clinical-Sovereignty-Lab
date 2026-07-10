# Cloudflare Edge Hardening — Public Trial Funnel (`try.html`)

**Status:** Manual dashboard configuration required — not automatable from this repo.
**Why manual:** The `CLOUDFLARE_PURGE_TOKEN` in `.env` is scoped to Cache Purge only (per
[`cloudflare-cache-purge-after-deploy.mdc`](../.cursor/rules/cloudflare-cache-purge-after-deploy.mdc)).
WAF/Rate Limiting Rules require a separate token scoped to `Zone WAF: Edit` and
`Zone Rate Limiting: Edit` (or equivalent "Firewall Services: Edit" permission group),
which has not been provisioned. Rather than requesting broader API credentials for a
one-time setup task, apply the rules below directly in the dashboard.

**Zone:** `sovereignsanctuary.net` — Zone ID `08f370c28164099f643acc472ee97db5` (Pro plan,
per [`cloudflare-infrastructure.mdc`](../.cursor/rules/cloudflare-infrastructure.mdc)).

## Why this layer matters (distinct from Turnstile + app-level caps)

Turnstile (shipped 2026-07-09, see `public_trial_gate.py` / `try.html`) gates
**`public_trial_start` and every `public_trial_chat` turn** — it stops a bot from
drawing free inference. It does **not** stop a bot from opening the WebSocket
connection itself thousands of times per minute; the `/ws` upgrade handshake happens
*before* any `public_trial_*` message is ever sent, so it's outside Turnstile's reach.
That handshake still costs the origin a TCP+TLS handshake, an nginx worker slot, and a
bridge coroutine — cheap per-request, but "cheap per request times unlimited IP
rotation" is exactly the abuse shape Cloudflare's edge is positioned to absorb before
any of it reaches `68.183.168.75`.

nginx already rate-limits `/ws` at the origin (`ws_limit` zone, 5r/s + burst 10 per
[`nginx.conf`](../nginx/nginx.conf) — verify against the live vhost per
[`nginx-production-vhost-safety.mdc`](../.cursor/rules/nginx-production-vhost-safety.mdc),
since production serves from `/etc/nginx/sites-enabled/`, not the repo template
directly). The Cloudflare rule below is a second, earlier layer: it rejects abusive
connection attempts at Cloudflare's network edge, so a rotating-IP burst never
consumes an origin TCP slot, an nginx worker, or a WireGuard hop in the first place.

## Step 1 — Rate Limiting Rule on `/ws` connection attempts

Dashboard path: **sovereignsanctuary.net → Security → WAF → Rate limiting rules → Create rule**

| Field | Value |
|---|---|
| Rule name | `ws-upgrade-rate-limit` |
| When incoming requests match | `(http.host eq "api.sovereignsanctuary.net" and http.request.uri.path eq "/ws")` |
| Rate | 20 requests |
| Period | 1 minute |
| Counting characteristic | IP address (default) |
| Action | Block |
| Duration | 10 minutes |
| With response status code | 429 |

Rationale for `20/min`: a real human opens `/ws` once per page load (occasionally
twice on a flaky reconnect). 20/min per IP comfortably covers a user with several
tabs/retries while still capping a scripted connection-flood from a single IP to
~1,200/hour instead of unbounded. This is intentionally *not* trial-specific — `/ws`
also serves logged-in client/coach/admin traffic, and no legitimate session opens 20
sockets in a minute, so applying it unconditionally is safe.

**If the trial's shared inference budget still depletes unusually fast after this rule
is live**, tighten further with a second, trial-specific rule matching on the
`Origin` request header instead of path alone:

| Field | Value |
|---|---|
| Rule name | `ws-upgrade-rate-limit-trial-origin` |
| When incoming requests match | `(http.host eq "api.sovereignsanctuary.net" and http.request.uri.path eq "/ws" and http.request.headers["origin"][0] eq "https://app.sovereignsanctuary.net")` |
| Rate | 8 requests |
| Period | 1 minute |
| Action | Managed Challenge (not Block — a Managed Challenge lets a real human through after solving it, whereas Block would also lock out anyone genuinely retrying `try.html`) |
| Duration | 15 minutes |

Only add this second rule if the first one alone isn't enough — start with the
broader, path-only rule and observe before narrowing.

## Step 2 — Confirm Bot Fight Mode is still active

Dashboard path: **Security → Bots**

Per `cloudflare-infrastructure.mdc`, **Super Bot Fight Mode** was already enabled
(2026-03-02) with "Definitely automated" traffic set to **Block**. Re-confirm this is
still the case — a plan change, a Cloudflare product migration, or a prior incident
response ("I'm Under Attack" mode toggled and reverted) can silently reset bot
settings. If "Definitely automated" has drifted to "Managed Challenge" or "Allow",
set it back to **Block**.

Do **not** enable **"Verified bots only"** globally — that would block legitimate
uptime monitors, Stripe/Twilio webhook senders, and SendGrid callbacks, none of which
are "verified bots" in Cloudflare's registry.

## Step 3 — WAF Managed Ruleset review (already partly live)

Dashboard path: **Security → WAF → Managed rules**

Confirm both are still **On** (per existing config, not new):
- Cloudflare Managed Ruleset
- OWASP Core Ruleset

No changes needed here unless the review turns up something drifted — this step is
verification, not new configuration.

## Step 4 — Alerting on abnormal edge traffic (optional, complements the app-level alert)

The application layer already alerts on-call when the shared trial budget depletes
unusually fast (`_alert_global_cap_depleted()` in `public_trial_gate.py`, triggered
when `global_daily_cap` or `global_hourly_cap` is hit — see
[`public_trial_funnel_4200095c.plan.md`](../.cursor/plans/public_trial_funnel_4200095c.plan.md)).
That alert fires from *inside* the budget being consumed. A Cloudflare-side signal
that fires *before* the budget is touched closes the loop:

Dashboard path: **Notifications → Add → Advanced Security Events Alert** (or
**Security → Events**, filter by `Action = Block`, `Rule = ws-upgrade-rate-limit`)

Configure an email/webhook notification when the `ws-upgrade-rate-limit` rule blocks
more than ~50 requests in a rolling hour. This is a genuine "an attack is happening
right now" signal, distinct from the app-level alert which fires only once the shared
turn budget has actually been drawn down.

## Verification after applying

```bash
# From a machine NOT already rate-limited, confirm normal /ws still upgrades:
curl -sI --http1.1 -H "Connection: Upgrade" -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  https://api.sovereignsanctuary.net/ws
# Expected: 101 Switching Protocols (not 429)

# Confirm the rule exists via the dashboard (no read-only API token provisioned for
# this) — Security → WAF → Rate limiting rules → "ws-upgrade-rate-limit" should show
# a nonzero "Requests matched" count within a few minutes of real traffic.
```

## What this does *not* replace

- **Turnstile remains the primary defense against scripted trial-turn abuse** — this
  Cloudflare layer only raises the cost of opening sockets in bulk; it does nothing
  once a socket is open and a human (or a bot that can solve Turnstile at real
  human cost) starts sending `public_trial_chat` messages within the caps already
  enforced server-side.
- **The global per-hour cap (`MAX_TRIAL_TURNS_PER_HOUR`) is unaffected either way** —
  it's a Postgres/Redis-backed budget inside `public_trial_gate.py`, not something
  Cloudflare needs to know about or duplicate.

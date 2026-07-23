# Sovereign IDE — YubiKey Hard Gate

## Goal

`https://ide.sovereignsanctuary.net` must not open from a Cloudflare bot challenge alone or a soft `sessionStorage` flag. A **live YubiKey** mints a short-lived cookie; the edge Worker rejects requests without it.

## Layers

| Layer | Role |
|---|---|
| Command `ide.html` | Admin session + **mandatory** WebAuthn every open; calls `auth-verify` with `issue_ide_session: true` |
| Backend `ide_session_gate.py` | HMAC token `ss_ide_session` (TTL default 4h); mint only after YubiKey |
| Worker `nate-ide-gate` | Route on `ide.sovereignsanctuary.net/*`; invalid → redirect to gateway |
| Cloudflare Access (recommended) | Zero Trust app on `ide.*`: admin email allowlist + **hardware key MFA** |
| Hive Defense | Still does **not** cover `ide.*` (GREEN API only) — do not rely on it |

## Deploy checklist

1. Set on GREEN `.env`: `IDE_GATE_SECRET=<openssl rand -hex 32>` (or rely on `JWT_SECRET` derivation). Recreate backend: `docker compose -f docker-compose.prod.yml up -d backend`.
2. Deploy API changes (`admin.py`, `ide_session_gate.py`) to GREEN (+ clone if applicable).
3. Deploy Worker:
   ```bash
   cd cloudflare/workers/nate-ide-gate
   npx wrangler secret put IDE_GATE_SECRET   # same value as GREEN
   npx wrangler deploy
   ```
4. Rsync `dashboard/ide.html` (+ `skyeye.html` for Command Terminal gate) to `/var/www/sovereign-command/` and reload host nginx.
5. Cloudflare Zero Trust → Access → Application → `ide.sovereignsanctuary.net`:
   - Include emails: admin only
   - Require MFA → hardware key / security key

## Verify

```bash
# No cookie → redirect / 401 (not code-server)
curl -sI https://ide.sovereignsanctuary.net | head -20

# After YubiKey via Command IDE tab, browser has ss_ide_session on .sovereignsanctuary.net
# Worker health:
curl -s https://ide.sovereignsanctuary.net/__ide_gate_health
```

## Command Terminal (SkyEye)

Separate second YubiKey gate: `last_yubikey_admin_terminal_at` (30 min TTL). Leaving the tab clears it. Command login YubiKey alone does **not** unlock the terminal.

# nate-mac-agent

Local Mac-side agent for CLI-Mac tool execution. Runs as a LaunchAgent (user-context), exposed through the Cloudflare Twin Engine tunnel.

## Setup

1. **Generate a shared token:**
   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
   Set this as `MAC_AGENT_TOKEN` in:
   - The plist file (`nate-mac-agent.plist`)
   - The VPS `.env` (for bridge + backend)

2. **Install and start:**
   ```bash
   cd backend/mac_agent
   ./install.sh
   ```

3. **Verify:**
   ```bash
   curl http://localhost:9900/health
   # Should return {"status": "ok", "agent": "nate-mac-agent", ...}
   ```

4. **Configure Cloudflare VPC service** (see below)

## Cloudflare VPC Service Setup

1. Go to Cloudflare Zero Trust dashboard > Networks > Tunnels
2. Select "Little Nate Twin Engine" tunnel (`d40e5315-...`)
3. Add a **Public Hostname** or **Private Network** service:
   - Service name: `nate-mac-agent`
   - Type: HTTP
   - URL: `localhost:9900`
4. Add an **Access Policy** restricting the service to the VPS connector identity only:
   - Go to Access > Applications > Add an application
   - Type: Self-hosted
   - Application domain: the VPC service hostname
   - Policy: Allow only the VPS service token / connector ID
   - Deny all other sources

Alternatively, add a second ingress rule to `~/.cloudflared/config.yml`:
```yaml
ingress:
  - hostname: mac-agent.internal.sovereignsanctuary.net
    service: http://localhost:9900
  - hostname: ""  # catch-all
    service: http://localhost:11434
```

## HOME_GPU via Twin (preferred — no public :11434)

Mac-agent proxies local Ollama behind the same bearer as CLI-Mac:

| Path | Upstream |
|------|----------|
| `GET/POST /ollama/{path}` | `http://127.0.0.1:11434/{path}` |

On GREEN `.env`:
```bash
HOME_GPU_URL=https://twin-agent.sovereignsanctuary.net/ollama
HOME_GPU_MODEL=qwen2.5-coder:14b-instruct-q5_K_M
# HOME_GPU_TOKEN defaults to MAC_AGENT_TOKEN when unset
```

Never publish Ollama as an unauthenticated Cloudflare hostname.

## Security Model

- **127.0.0.1 binding**: Agent only listens on localhost. The Cloudflare tunnel connects to localhost:9900.
- **Bearer token auth**: Every request (except GET /health) requires `Authorization: Bearer <MAC_AGENT_TOKEN>`.
- **Command allowlist**: Only explicitly permitted command prefixes are allowed. No blocklist.
- **shell=False enforcement**: Commands run via `subprocess` with `shell=False`. Shell metacharacters (`;|&$\`()`) are rejected pre-execution.
- **Workspace mutex**: Per-directory `asyncio.Lock` prevents concurrent conflicting operations.
- **Red-zone paths**: File operations on `/etc/`, `/System/`, `/Library/`, `~/.ssh/id_*`, `.env` files are blocked.
- **Audit log**: All operations logged to `data/mac_agent_audit.jsonl`.

## Upgrade

Run `./install.sh` again. It handles unload/copy/reload automatically.

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/net.sovereignsanctuary.nate-mac-agent.plist
rm ~/Library/LaunchAgents/net.sovereignsanctuary.nate-mac-agent.plist
```

## Tests

```bash
cd backend/mac_agent
MAC_AGENT_TOKEN=your-token python3 -m pytest test_mac_agent.py -v
```

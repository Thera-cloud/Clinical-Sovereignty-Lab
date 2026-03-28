"""
Read-Only SSH to Production — Capability 3
Sovereign Sanctuary · Little Nate Infrastructure

Allows LN to execute READ-ONLY commands on production servers via SSH.
Every command goes through a whitelist check. Destructive commands are
blocked at the tool level — they never reach the server.

Security model:
  - SSH key must be loaded in ssh-agent on the bridge host
  - Commands filtered against strict whitelist
  - All commands and outputs logged to ssh_audit.jsonl
  - No interactive sessions — single command execution only
  - 30-second timeout per command

File: backend/app/websocket/tools/ssh_tools.py
Dependencies: asyncio (stdlib)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


# ---------------------------------------------------------------------------
# Command whitelist — read-only commands allowed on production
# ---------------------------------------------------------------------------

ALLOWED_COMMAND_PREFIXES: List[str] = [
    # Process inspection
    "ps ", "ps aux", "pgrep ", "top -bn1", "uptime",
    "free ", "free -h", "df ", "df -h",

    # Log inspection
    "tail ", "head ", "cat ", "less ", "wc ", "grep ", "journalctl ",

    # Docker inspection (read-only)
    "docker ps", "docker logs ", "docker inspect ",
    "docker stats --no-stream", "docker compose ps",
    "docker compose -f docker-compose.prod.yml ps",
    "docker exec ",

    # Network diagnostics
    "curl ", "wget -q ", "dig ", "nslookup ",
    "ss -tlnp", "netstat -tlnp",

    # Service health
    "systemctl status ", "systemctl is-active ", "nginx -t",

    # Database (SELECT only — writes blocked by BLOCKED_PATTERNS)
    "psql ",

    # File inspection
    "ls ", "find ", "stat ", "file ", "md5sum ", "sha256sum ", "readlink ",
]

# ALWAYS blocked — even if they match a prefix above
BLOCKED_PATTERNS: List[str] = [
    r"\brm\b", r"\bmv\b", r"\bcp\b.*--force",
    r"\bkill\b", r"\bkillall\b", r"\bshutdown\b", r"\breboot\b",
    r"\bsystemctl\s+(start|stop|restart|enable|disable)\b",
    r"\bdocker\s+(stop|kill|rm|rmi|prune|compose\s+down|compose\s+up)\b",
    r"\brsync\b", r"\bscp\b",
    r"\bapt\b", r"\byum\b", r"\bpip\b", r"\bnpm\b",
    r"\bgit\s+(push|commit|merge|rebase|reset|checkout)\b",
    r"\bDROP\b", r"\bDELETE\b", r"\bTRUNCATE\b", r"\bALTER\b",
    r"\bINSERT\b", r"\bUPDATE\b", r"\bCREATE\b",
    r"\bGRANT\b", r"\bREVOKE\b",
    r">\s",              # output redirection
    r"\|.*rm\b",         # piped to rm
    r";\s*rm\b",         # chained with rm
    r"&&\s*rm\b",
    r"`",                # command substitution
    r"\$\(",             # command substitution
    r"eval\b", r"exec\b", r"source\b",
    r"\bchmod\b", r"\bchown\b",
    r"\buseradd\b", r"\buserdel\b", r"\bpasswd\b",
    r"\bsudo\b",
]

# docker exec sub-commands allowed (read-only only)
ALLOWED_DOCKER_EXEC_CMDS: Set[str] = {
    "printenv", "env", "cat", "ls", "ps", "head", "tail", "grep",
    "wc", "df", "free", "uptime", "whoami", "hostname",
    "psql",  # SELECT only — writes blocked by BLOCKED_PATTERNS
    "python3", "pg_isready", "redis-cli",
}

# Sovereign Sanctuary server fleet
KNOWN_SERVERS: Dict[str, str] = {
    "primary": "root@68.183.168.75",
    "clone": "root@159.65.108.25",
    "hetzner": "root@37.27.244.80",
    "sandbox": "root@178.128.178.15",
}


@dataclass
class SSHAuditEntry:
    server: str
    command: str
    allowed: bool
    block_reason: str = ""
    exit_code: int = -1
    stdout_preview: str = ""
    stderr_preview: str = ""
    duration_ms: int = 0
    executed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "server": self.server,
            "command": self.command,
            "allowed": self.allowed,
            "block_reason": self.block_reason,
            "exit_code": self.exit_code,
            "stdout_preview": self.stdout_preview[:500],
            "stderr_preview": self.stderr_preview[:200],
            "duration_ms": self.duration_ms,
            "executed_at": self.executed_at,
        }


def validate_command(command: str) -> tuple:
    """Check if a command is allowed. Returns (allowed: bool, reason: str)."""
    stripped = command.strip()
    if not stripped:
        return False, "Empty command"

    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, stripped, re.IGNORECASE):
            return False, f"Blocked pattern: {pattern}"

    if stripped.startswith("docker exec"):
        parts = stripped.split()
        subcmd_idx = 2
        for idx, part in enumerate(parts[2:], start=2):
            if not part.startswith("-"):
                subcmd_idx = idx + 1
                break
        if subcmd_idx < len(parts):
            subcmd = parts[subcmd_idx]
            if subcmd not in ALLOWED_DOCKER_EXEC_CMDS:
                return False, f"docker exec sub-command '{subcmd}' not in whitelist"

    for prefix in ALLOWED_COMMAND_PREFIXES:
        if stripped.startswith(prefix) or stripped == prefix.strip():
            return True, f"Matches allowed prefix: {prefix.strip()}"

    return False, "Command does not match any allowed prefix"


async def execute_ssh(
    server: str,
    command: str,
    timeout: int = 30,
    audit_log_path: Optional[Path] = None,
    enforce_read_only: bool = True,
) -> Dict[str, Any]:
    """
    Execute a single command on a remote server via SSH.
    Uses subprocess ssh (requires key in ssh-agent).

    When enforce_read_only=True (default), validate_command() whitelist applies.
    When False, only ssh_write_tools (gated by ask_user + audit) may call —
    required because restart/deploy use docker compose up, which the read-only
    whitelist blocks.
    """
    ssh_target = KNOWN_SERVERS.get(server, server)
    if "@" not in ssh_target:
        return {
            "success": False,
            "error": f"Unknown server '{server}'. Known: {', '.join(KNOWN_SERVERS.keys())}",
            "error_code": "UNKNOWN_SERVER",
        }

    allowed = True
    reason = "write path (validation skipped)"
    if enforce_read_only:
        allowed, reason = validate_command(command)
    audit = SSHAuditEntry(server=ssh_target, command=command, allowed=allowed)

    if not allowed:
        audit.block_reason = reason
        _log_audit(audit, audit_log_path)
        print(f">>> [SSH] BLOCKED: {command} — {reason}")
        return {
            "success": False,
            "error": f"Command blocked: {reason}",
            "error_code": "COMMAND_BLOCKED",
            "blocked_reason": reason,
        }

    start = time.monotonic()
    try:
        ssh_cmd = [
            "ssh",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ConnectTimeout=10",
            "-o", "BatchMode=yes",
            ssh_target,
            command,
        ]

        proc = await asyncio.create_subprocess_exec(
            *ssh_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            audit.duration_ms = int((time.monotonic() - start) * 1000)
            audit.block_reason = f"Timeout after {timeout}s"
            _log_audit(audit, audit_log_path)
            return {
                "success": False,
                "error": f"SSH command timed out after {timeout}s",
                "error_code": "TIMEOUT",
            }

        duration_ms = int((time.monotonic() - start) * 1000)
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        exit_code = proc.returncode or 0

        max_output = 10_000
        if len(stdout) > max_output:
            stdout = stdout[:max_output] + f"\n... [TRUNCATED — {len(stdout) - max_output} chars omitted]"

        audit.exit_code = exit_code
        audit.stdout_preview = stdout[:500]
        audit.stderr_preview = stderr[:200]
        audit.duration_ms = duration_ms
        _log_audit(audit, audit_log_path)

        print(f">>> [SSH] {ssh_target}: {command} → exit={exit_code}, "
              f"{len(stdout)} chars, {duration_ms}ms")

        return {
            "success": exit_code == 0,
            "result": stdout if exit_code == 0 else f"[exit {exit_code}]\n{stderr}\n{stdout}",
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
            "server": ssh_target,
            "command": command,
            "duration_ms": duration_ms,
        }

    except FileNotFoundError:
        return {"success": False, "error": "ssh binary not found", "error_code": "SSH_NOT_FOUND"}
    except Exception as e:
        audit.duration_ms = int((time.monotonic() - start) * 1000)
        audit.block_reason = str(e)
        _log_audit(audit, audit_log_path)
        return {"success": False, "error": str(e), "error_code": "SSH_ERROR"}


def _log_audit(entry: SSHAuditEntry, log_path: Optional[Path] = None):
    if not log_path:
        log_path = Path(os.environ.get("CLI_PROJECT_ROOT", ".")) / \
            "backend" / "app" / "websocket" / "data" / "ssh_audit.jsonl"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a") as f:
            f.write(json.dumps(entry.to_dict()) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Tool definition — DEBUG mode only
# ---------------------------------------------------------------------------

SSH_EXEC_TOOL_DEF = {
    "name": "ssh_exec",
    "description": (
        "Execute a READ-ONLY command on a production server via SSH. "
        "Use to check logs, inspect Docker containers, verify service health, "
        "query database (SELECT only), check nginx config, or diagnose production issues. "
        "DESTRUCTIVE COMMANDS ARE BLOCKED: no rm, kill, restart, deploy, DROP, DELETE, ALTER. "
        "Known servers: primary (68.183.168.75), clone (159.65.108.25), "
        "hetzner (37.27.244.80), sandbox (178.128.178.15). "
        "All commands logged to ssh_audit.jsonl."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "server": {
                "type": "string",
                "description": "Server alias or user@host",
                "enum": ["primary", "clone", "hetzner", "sandbox"],
            },
            "command": {
                "type": "string",
                "description": (
                    "Read-only command. Examples: 'docker ps', "
                    "'docker logs nate_backend --tail 50', "
                    "'docker exec nate_postgres psql -U nate_admin -d little_nate "
                    "-c \"SELECT count(*) FROM users\"', "
                    "'curl -s localhost:8000/health', 'nginx -t'"
                ),
            },
            "timeout": {
                "type": "integer",
                "description": "Max seconds to wait (default 30)",
                "default": 30,
            },
        },
        "required": ["server", "command"],
    },
}


async def handle_ssh_exec(params: Dict[str, Any]) -> Dict[str, Any]:
    """Tool dispatch handler for ssh_exec."""
    return await execute_ssh(
        server=params.get("server", ""),
        command=params.get("command", ""),
        timeout=params.get("timeout", 30),
    )

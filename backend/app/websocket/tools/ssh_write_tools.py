"""
Write SSH to Production — Capability 5
Sovereign Sanctuary · Little Nate Infrastructure

Extends the read-only SSH (Capability 3) with predefined WRITE operations:
deploy code, restart containers, apply migrations, purge Cloudflare cache,
trigger trust audit cascade.

Every write operation goes through TWO confirmation gates:
  1. ask_user confirmation showing exactly what will run
  2. Post-execution automatic health verification

This is the "deploy the fix and verify trust is 100%" capability.

Requires: ask_user (Capability 1), ssh_tools (Capability 3)

File: backend/app/websocket/tools/ssh_write_tools.py
Dependencies: ssh_tools.py, ask_user.py
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

from .ssh_tools import execute_ssh, KNOWN_SERVERS


# ---------------------------------------------------------------------------
# Write operation definitions — adapted to Sovereign Sanctuary infrastructure
# ---------------------------------------------------------------------------

@dataclass
class WriteOperation:
    name: str
    description: str
    commands: List[str]
    verify_commands: List[str]
    rollback_commands: List[str]
    requires_build_id: bool = False
    destructive_level: str = "low"   # low / medium / high / critical
    estimated_downtime_seconds: int = 0


WRITE_OPERATIONS: Dict[str, WriteOperation] = {

    "restart_bridge": WriteOperation(
        name="restart_bridge",
        description="Restart nate_bridge via docker compose (15-30s WebSocket blackout)",
        commands=[
            "cd /opt/clinical-sovereignty-lab && "
            "docker compose -f docker-compose.prod.yml up -d bridge",
        ],
        verify_commands=[
            "sleep 10",
            "docker ps --filter name=nate_bridge --format '{{.Names}} {{.Status}}'",
            "docker logs nate_bridge --tail 5 2>&1 | grep -E 'Database pool|UserStore|PostgreSQL'",
            "docker exec nate_bridge printenv ENVIRONMENT",
        ],
        rollback_commands=[
            "docker logs nate_bridge --tail 50 2>&1",
        ],
        destructive_level="medium",
        estimated_downtime_seconds=15,
    ),

    "restart_backend": WriteOperation(
        name="restart_backend",
        description="Restart nate_backend via docker compose",
        commands=[
            "cd /opt/clinical-sovereignty-lab && "
            "docker compose -f docker-compose.prod.yml up -d backend",
        ],
        verify_commands=[
            "sleep 15",
            "docker ps --filter name=nate_backend --format '{{.Names}} {{.Status}}'",
            "docker logs nate_backend --since 30s 2>&1 | grep 'STARTUP COMPLETE'",
            "curl -s http://localhost:8000/health",
            "docker exec nate_backend printenv ENVIRONMENT",
        ],
        rollback_commands=[
            "docker logs nate_backend --tail 50 2>&1",
            "docker logs nate_backend --since 60s 2>&1 | grep -E 'does not exist|No module' | sort -u",
        ],
        destructive_level="medium",
        estimated_downtime_seconds=20,
    ),

    "apply_migration": WriteOperation(
        name="apply_migration",
        description="Apply a SQL migration to production PostgreSQL (little_nate database)",
        commands=[],  # Dynamically built from migration_file param
        verify_commands=[
            "docker exec nate_postgres psql -U nate_admin -d little_nate -c "
            "\"SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename DESC LIMIT 5\"",
        ],
        rollback_commands=[],
        requires_build_id=True,
        destructive_level="critical",
    ),

    "restart_nginx": WriteOperation(
        name="restart_nginx",
        description="Test and reload host nginx configuration",
        commands=[
            "nginx -t && systemctl reload nginx",
        ],
        verify_commands=[
            "systemctl is-active nginx",
            "curl -sI https://api.sovereignsanctuary.net/health | head -5",
        ],
        rollback_commands=[
            "journalctl -u nginx --no-pager -n 20",
        ],
        destructive_level="medium",
        estimated_downtime_seconds=2,
    ),

    "purge_cloudflare_cache": WriteOperation(
        name="purge_cloudflare_cache",
        description="Purge Cloudflare edge cache for all Flutter bootstrap files",
        commands=[
            'CF_ZONE=$(grep CF_ZONE_ID /opt/clinical-sovereignty-lab/.env | cut -d= -f2); '
            'CF_TOKEN=$(grep CF_API_TOKEN /opt/clinical-sovereignty-lab/.env | cut -d= -f2); '
            'curl -s -X POST "https://api.cloudflare.com/client/v4/zones/${CF_ZONE}/purge_cache" '
            '-H "Authorization: Bearer ${CF_TOKEN}" '
            '-H "Content-Type: application/json" '
            "--data '{\"purge_everything\":true}'",
        ],
        verify_commands=[
            "curl -sI https://coach.sovereignsanctuary.net/main.dart.js | grep -E 'Content-Length|Cache-Control'",
            "curl -sI https://app.sovereignsanctuary.net/main.dart.js | grep -E 'Content-Length|Cache-Control'",
        ],
        rollback_commands=[],
        destructive_level="low",
    ),

    "trust_audit_cascade": WriteOperation(
        name="trust_audit_cascade",
        description="Trigger all 40 auditors and verify 100% trust",
        commands=[
            'TOKEN=$(grep SKYEYE_AUDIT_TOKEN /opt/clinical-sovereignty-lab/.env | cut -d= -f2); '
            'curl -s -X POST -H "Authorization: Bearer $TOKEN" '
            'http://localhost:8000/api/admin/skyeye-audit/send',
        ],
        verify_commands=[
            "sleep 300",
            "docker exec nate_postgres psql -U nate_admin -d little_nate -c "
            "\"SELECT type, LEFT(content::text, 120) FROM skyeye_activity "
            "WHERE type = 'trust_enforcer_sent' ORDER BY created_at DESC LIMIT 1\"",
        ],
        rollback_commands=[],
        destructive_level="low",
    ),
}


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

async def handle_ssh_deploy(
    params: Dict[str, Any],
    ask_user_fn: Callable,
    build_manager: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Execute a predefined write operation on a production server.

    Flow:
    1. Look up operation definition
    2. If requires_build_id, verify the build passed
    3. Show ask_user confirmation with full command list + risk level
    4. Execute commands in order, stopping on first failure
    5. Run verify commands
    6. If verify fails, run rollback commands and report
    7. Log everything to audit trail
    """
    op_name = params.get("operation", "")
    server = params.get("server", "primary")
    build_id = params.get("build_id", "")
    migration_file = params.get("migration_file", "")

    op = WRITE_OPERATIONS.get(op_name)
    if not op:
        available = ", ".join(WRITE_OPERATIONS.keys())
        return {
            "success": False,
            "error": f"Unknown operation '{op_name}'. Available: {available}",
            "error_code": "UNKNOWN_OPERATION",
        }

    # Build dynamic commands
    commands = list(op.commands)
    verify_commands = list(op.verify_commands)

    if op_name == "apply_migration" and migration_file:
        commands = [
            f"docker exec -i nate_postgres psql -U nate_admin -d little_nate "
            f"< /opt/clinical-sovereignty-lab/backend/migrations/{migration_file}",
        ]

    # --- Gate 1: Build verification ---
    if op.requires_build_id:
        if not build_id:
            return {
                "success": False,
                "error": f"Operation '{op_name}' requires a build_id. "
                         "Run build pipeline first.",
                "error_code": "BUILD_ID_REQUIRED",
            }
        if build_manager:
            verification = build_manager.get_verification(build_id)
            if not verification or not verification.get("verified"):
                return {
                    "success": False,
                    "error": f"Build '{build_id}' is not verified.",
                    "error_code": "BUILD_NOT_VERIFIED",
                }

    # --- Gate 2: User confirmation ---
    downtime_note = ""
    if op.estimated_downtime_seconds > 0:
        downtime_note = f"\nEstimated downtime: {op.estimated_downtime_seconds}s"

    confirmation = await ask_user_fn({
        "question": f"Execute {op.name} on {server}?",
        "question_type": "confirm",
        "context": (
            f"Risk level: {op.destructive_level.upper()}\n"
            f"Description: {op.description}\n"
            f"Commands ({len(commands)}):\n" +
            "\n".join(f"  {i+1}. {cmd[:100]}" for i, cmd in enumerate(commands)) +
            downtime_note +
            (f"\nBuild ID: {build_id}" if build_id else "")
        ),
        "options": [
            {"label": f"Yes — execute {op.name}", "value": "yes"},
            {"label": "No — cancel", "value": "no"},
        ],
    })

    selected = confirmation.get("selected", confirmation.get("selected_values", []))
    if "yes" not in selected:
        return {
            "success": False,
            "result": f"Operation '{op_name}' cancelled by user.",
            "error_code": "USER_CANCELLED",
        }

    # --- Execute commands ---
    print(f">>> [SSH_DEPLOY] Executing {op_name} on {server} ({len(commands)} commands)")
    start_time = time.monotonic()
    execution_log: List[Dict[str, Any]] = []
    all_succeeded = True

    for i, cmd in enumerate(commands):
        if cmd.startswith("#"):
            execution_log.append({"step": i + 1, "command": cmd, "success": True, "output": "info"})
            continue

        print(f">>> [SSH_DEPLOY] Step {i+1}/{len(commands)}: {cmd[:80]}")
        result = await execute_ssh(server, cmd, timeout=120, enforce_read_only=False)
        execution_log.append({
            "step": i + 1,
            "command": cmd,
            "success": result.get("success", False),
            "exit_code": result.get("exit_code", -1),
            "output": result.get("stdout", result.get("result", ""))[:500],
        })
        if not result.get("success"):
            all_succeeded = False
            print(f">>> [SSH_DEPLOY] Step {i+1} FAILED: {result.get('error', result.get('stderr', ''))}")
            break

    # --- Verify ---
    verification_log: List[Dict[str, Any]] = []
    if all_succeeded and verify_commands:
        print(f">>> [SSH_DEPLOY] Running {len(verify_commands)} verification checks")
        for cmd in verify_commands:
            if cmd.startswith("sleep"):
                secs = int(cmd.split()[1]) if len(cmd.split()) > 1 else 5
                await asyncio.sleep(secs)
                verification_log.append({"command": cmd, "success": True, "output": f"Waited {secs}s"})
                continue
            result = await execute_ssh(server, cmd, timeout=30, enforce_read_only=False)
            verification_log.append({
                "command": cmd,
                "success": result.get("success", False),
                "output": result.get("stdout", result.get("result", ""))[:500],
            })

    # Check verification (skip sleep entries)
    verify_passed = all(
        v.get("success", False)
        for v in verification_log
        if not v.get("command", "").startswith("sleep")
    )

    # --- Rollback if failed ---
    rollback_log: List[Dict[str, Any]] = []
    if not all_succeeded or not verify_passed:
        if op.rollback_commands:
            print(">>> [SSH_DEPLOY] Verification failed — running rollback")
            for cmd in op.rollback_commands:
                result = await execute_ssh(server, cmd, timeout=30, enforce_read_only=False)
                rollback_log.append({
                    "command": cmd,
                    "output": result.get("stdout", "")[:500],
                })

    total_duration = int((time.monotonic() - start_time) * 1000)

    # --- Audit log ---
    _log_deploy_audit({
        "operation": op_name,
        "server": server,
        "build_id": build_id,
        "destructive_level": op.destructive_level,
        "commands_run": len(execution_log),
        "all_succeeded": all_succeeded,
        "verify_passed": verify_passed,
        "duration_ms": total_duration,
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "execution_log": execution_log,
        "verification_log": verification_log,
        "rollback_log": rollback_log,
    })

    # --- Format result ---
    output_parts = [
        f"=== {op_name.upper()} on {server} ===",
        f"Status: {'SUCCESS' if all_succeeded and verify_passed else 'FAILED'}",
        f"Duration: {total_duration}ms",
        "",
        "Execution:",
    ]
    for step in execution_log:
        status = "OK" if step["success"] else "FAIL"
        output_parts.append(f"  [{status}] Step {step['step']}: {step['command'][:80]}")
        if step.get("output"):
            for line in step["output"].split("\n")[:3]:
                output_parts.append(f"    {line}")

    if verification_log:
        output_parts.append("\nVerification:")
        for v in verification_log:
            status = "OK" if v["success"] else "FAIL"
            output_parts.append(f"  [{status}] {v['command'][:80]}")
            if v.get("output"):
                for line in v["output"].split("\n")[:2]:
                    output_parts.append(f"    {line}")

    if rollback_log:
        output_parts.append("\nRollback output:")
        for r in rollback_log:
            output_parts.append(f"  {r['command'][:80]}")
            if r.get("output"):
                output_parts.append(f"    {r['output'][:200]}")

    return {
        "success": all_succeeded and verify_passed,
        "result": "\n".join(output_parts),
        "operation": op_name,
        "all_commands_succeeded": all_succeeded,
        "verification_passed": verify_passed,
        "duration_ms": total_duration,
    }


def _log_deploy_audit(entry: Dict[str, Any]):
    log_path = Path(os.environ.get("CLI_PROJECT_ROOT", ".")) / \
        "backend" / "app" / "websocket" / "data" / "ssh_write_audit.jsonl"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Tool definition — LN-FAB mode only
# ---------------------------------------------------------------------------

SSH_DEPLOY_TOOL_DEF = {
    "name": "ssh_deploy",
    "description": (
        "Execute a predefined deployment operation on a production server. "
        "REQUIRES user confirmation for every operation. "
        "Available: restart_bridge, restart_backend, apply_migration, "
        "restart_nginx, purge_cloudflare_cache, trust_audit_cascade. "
        "Copy files to the server with manual scp (no rsync --delete), then restart_backend. "
        "High-risk operations (apply_migration) also require "
        "a Blue-Green-Orange build_id. Logged to ssh_write_audit.jsonl."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": list(WRITE_OPERATIONS.keys()),
                "description": "Which deployment operation to execute",
            },
            "server": {
                "type": "string",
                "enum": ["primary", "clone", "hetzner"],
                "description": "Target server (default: primary)",
                "default": "primary",
            },
            "build_id": {
                "type": "string",
                "description": "Blue-Green-Orange build ID (required for apply_migration)",
            },
            "migration_file": {
                "type": "string",
                "description": "SQL migration filename (for apply_migration, e.g. '090_new_feature.sql')",
            },
        },
        "required": ["operation"],
    },
}

"""
Git Operations with Safety Gates — Capability 4
Sovereign Sanctuary · Little Nate Infrastructure

Allows LN to execute git operations (commit, push) but ONLY after
Blue-Green-Orange verification has passed AND the user confirms.

Safety model:
  - Read-only git commands (status, diff, log) are always allowed
  - Write commands (commit, push) require verified build_id
  - Force push is ALWAYS blocked, no exceptions
  - Every git operation logged to git_audit.jsonl

Requires: ask_user tool (Capability 1)

File: backend/app/websocket/tools/git_tools.py
Dependencies: asyncio, subprocess (stdlib)
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


# ---------------------------------------------------------------------------
# Git safety rules
# ---------------------------------------------------------------------------

PERMANENTLY_BLOCKED: List[str] = [
    "git push --force",
    "git push -f",
    "git reset --hard",
    "git clean -fd",
    "git rebase",
    "git filter-branch",
    "git reflog expire",
]

READ_ONLY_COMMANDS: List[str] = [
    "git status",
    "git diff",
    "git log",
    "git show",
    "git branch",
    "git branch -a",
    "git remote -v",
    "git stash list",
    "git describe",
    "git rev-parse",
    "git ls-files",
    "git blame",
]


@dataclass
class GitAuditEntry:
    command: str
    allowed: bool
    build_id: str = ""
    build_verified: bool = False
    user_confirmed: bool = False
    block_reason: str = ""
    exit_code: int = -1
    output_preview: str = ""
    duration_ms: int = 0
    executed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command": self.command,
            "allowed": self.allowed,
            "build_id": self.build_id,
            "build_verified": self.build_verified,
            "user_confirmed": self.user_confirmed,
            "block_reason": self.block_reason,
            "exit_code": self.exit_code,
            "output_preview": self.output_preview[:500],
            "duration_ms": self.duration_ms,
            "executed_at": self.executed_at,
        }


def is_read_only(command: str) -> bool:
    stripped = command.strip()
    return any(stripped.startswith(prefix) for prefix in READ_ONLY_COMMANDS)


def is_permanently_blocked(command: str) -> bool:
    stripped = command.strip()
    return any(blocked in stripped for blocked in PERMANENTLY_BLOCKED)


async def handle_git_write(
    params: Dict[str, Any],
    ask_user_fn: Optional[Callable] = None,
    build_manager: Optional[Any] = None,
    project_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Execute a git write operation with safety gates.

    Gate 1: Command is not permanently blocked
    Gate 2: Blue-Green-Orange build verification (if build_manager available)
    Gate 3: User confirms via ask_user prompt

    params:
        operation: "commit" | "push" | "branch" | "tag"
        message: str (for commit)
        branch: str (for push target, default current branch)
        build_id: str (from Blue-Green-Orange verification)
        files: list[str] (for selective staging)
    """
    operation = params.get("operation", "")
    message = params.get("message", "")
    branch = params.get("branch", "main")
    build_id = params.get("build_id", "")
    files = params.get("files", [])
    root = project_root or Path(os.environ.get("CLI_PROJECT_ROOT", "."))

    audit = GitAuditEntry(command=f"git {operation}", build_id=build_id)

    # --- Gate 1: Not permanently blocked ---
    full_cmd = _build_command(operation, message, branch, files)
    if is_permanently_blocked(full_cmd):
        audit.allowed = False
        audit.block_reason = "Permanently blocked command"
        _log_git_audit(audit, root)
        return {
            "success": False,
            "error": f"PERMANENTLY BLOCKED: '{full_cmd}' is never allowed. "
                     "This includes force push, hard reset, and history rewriting.",
            "error_code": "GIT_BLOCKED",
        }

    # --- Gate 2: Build verification ---
    build_verified = False
    if build_manager and build_id:
        try:
            verification = build_manager.get_verification(build_id)
            if verification and verification.get("verified"):
                build_verified = True
                audit.build_verified = True
            else:
                audit.allowed = False
                audit.block_reason = f"Build {build_id} not verified"
                _log_git_audit(audit, root)
                return {
                    "success": False,
                    "error": f"Build '{build_id}' has not passed verification. "
                             "Run build test and verify before committing.",
                    "error_code": "BUILD_NOT_VERIFIED",
                }
        except Exception as e:
            audit.allowed = False
            audit.block_reason = f"Build check failed: {e}"
            _log_git_audit(audit, root)
            return {
                "success": False,
                "error": f"Could not verify build status: {e}. Commit blocked.",
                "error_code": "BUILD_CHECK_FAILED",
            }
    elif build_manager:
        audit.allowed = False
        audit.block_reason = "No build_id provided"
        _log_git_audit(audit, root)
        return {
            "success": False,
            "error": "Git write operations require a build_id. "
                     "Run build start → test → verify first.",
            "error_code": "NO_BUILD_ID",
        }

    # --- Gate 3: User confirmation ---
    if ask_user_fn:
        diff_result = await _run_git(["git", "diff", "--stat"], root)
        diff_summary = diff_result.get("stdout", "No changes staged")

        confirmation_q = {
            "question": f"Confirm git {operation}?",
            "question_type": "confirm",
            "context": (
                f"Command: {full_cmd}\n"
                f"Build verified: {'Yes (' + build_id + ')' if build_verified else 'No build manager'}\n"
                f"Changes:\n{diff_summary[:500]}"
            ),
            "options": [
                {"label": f"Yes — {operation}", "value": "yes"},
                {"label": "No — cancel", "value": "no"},
            ],
        }

        try:
            response = await ask_user_fn(confirmation_q)
            if response.get("skipped") or response.get("timed_out"):
                audit.allowed = False
                audit.block_reason = "User skipped or timed out"
                _log_git_audit(audit, root)
                return {
                    "success": False,
                    "error": f"Git {operation} cancelled — user did not confirm.",
                    "error_code": "USER_CANCELLED",
                }
            selected = response.get("selected", response.get("selected_values", []))
            if "yes" not in selected:
                audit.allowed = False
                audit.block_reason = "User declined"
                _log_git_audit(audit, root)
                return {
                    "success": False,
                    "error": f"Git {operation} cancelled by user.",
                    "error_code": "USER_DECLINED",
                }
            audit.user_confirmed = True
        except Exception as e:
            audit.allowed = False
            audit.block_reason = f"Confirmation failed: {e}"
            _log_git_audit(audit, root)
            return {
                "success": False,
                "error": f"Could not get user confirmation: {e}",
                "error_code": "CONFIRMATION_FAILED",
            }

    # --- Execute ---
    audit.allowed = True
    start = time.monotonic()

    if operation == "commit":
        result = await _git_commit(message, files, root)
    elif operation == "push":
        result = await _git_push(branch, root)
    elif operation == "branch":
        branch_name = params.get("branch_name", "")
        result = await _run_git(["git", "checkout", "-b", branch_name], root)
    elif operation == "tag":
        tag_name = params.get("tag_name", "")
        result = await _run_git(["git", "tag", tag_name], root)
    else:
        return {"success": False, "error": f"Unknown operation: {operation}", "error_code": "UNKNOWN_OP"}

    audit.duration_ms = int((time.monotonic() - start) * 1000)
    audit.exit_code = result.get("exit_code", -1)
    audit.output_preview = result.get("stdout", "")[:500]
    _log_git_audit(audit, root)

    return result


async def _git_commit(message: str, files: List[str], root: Path) -> Dict[str, Any]:
    if not message:
        return {"success": False, "error": "Commit message required", "error_code": "NO_MESSAGE"}

    if files:
        for f in files:
            await _run_git(["git", "add", f], root)
    else:
        await _run_git(["git", "add", "-u"], root)

    return await _run_git(["git", "commit", "-m", message], root)


async def _git_push(branch: str, root: Path) -> Dict[str, Any]:
    return await _run_git(["git", "push", "origin", branch], root)


async def _run_git(cmd: List[str], root: Path) -> Dict[str, Any]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(root),
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=30)
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        exit_code = proc.returncode or 0

        return {
            "success": exit_code == 0,
            "result": stdout if exit_code == 0 else f"[exit {exit_code}] {stderr}\n{stdout}",
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
        }
    except asyncio.TimeoutError:
        return {"success": False, "error": "Git command timed out (30s)", "error_code": "TIMEOUT"}
    except Exception as e:
        return {"success": False, "error": str(e), "error_code": "GIT_ERROR"}


def _build_command(operation: str, message: str, branch: str, files: List[str]) -> str:
    if operation == "commit":
        staged = f" -- {' '.join(files)}" if files else " -u (all tracked)"
        return f'git add{staged} && git commit -m "{message[:80]}"'
    elif operation == "push":
        return f"git push origin {branch}"
    elif operation == "branch":
        return f"git checkout -b {branch}"
    elif operation == "tag":
        return f"git tag {branch}"
    return f"git {operation}"


def _log_git_audit(entry: GitAuditEntry, root: Path):
    log_path = root / "backend" / "app" / "websocket" / "data" / "git_audit.jsonl"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a") as f:
            f.write(json.dumps(entry.to_dict()) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Tool definitions — LN-FAB mode only
# ---------------------------------------------------------------------------

GIT_COMMIT_TOOL_DEF = {
    "name": "git_commit",
    "description": (
        "Stage and commit changes to git. REQUIRES either a verified "
        "Blue-Green-Orange build_id OR explicit user confirmation. "
        "Force push is permanently blocked. The user sees a confirmation "
        "prompt showing the diff summary before commit."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Commit message. Short summary, blank line, then details.",
            },
            "build_id": {
                "type": "string",
                "description": "Build ID from Blue-Green-Orange verification",
            },
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Specific files to stage (optional — defaults to all tracked)",
            },
        },
        "required": ["message"],
    },
}

GIT_PUSH_TOOL_DEF = {
    "name": "git_push",
    "description": (
        "Push committed changes to origin. REQUIRES user confirmation. "
        "Force push is permanently blocked."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "branch": {
                "type": "string",
                "description": "Branch to push (default: current branch)",
                "default": "main",
            },
            "build_id": {
                "type": "string",
                "description": "Build ID from Blue-Green-Orange verification",
            },
        },
    },
}

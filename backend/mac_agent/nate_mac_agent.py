"""
nate-mac-agent: Local Mac-side agent for CLI-Mac tool execution.

Runs on the Mac as a LaunchAgent (user-context), exposed through the
Cloudflare Twin Engine tunnel as a VPC service. The bridge and backend
forward CLI-Mac write/shell/build/git/process commands here instead of
executing inside the Docker container.

Security:
  - Binds to 127.0.0.1 ONLY (never 0.0.0.0)
  - Bearer token auth (MAC_AGENT_TOKEN)
  - Command allowlist with shell=False enforcement
  - Red-zone path protection for file operations
  - Per-workspace asyncio.Lock mutex for concurrent execution
  - Audit log to mac_agent_audit.jsonl
"""

import asyncio
import json
import logging
import os
import signal
import shlex
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiofiles
import psutil
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

# ── Configuration ──

MAC_AGENT_TOKEN = os.getenv("MAC_AGENT_TOKEN", "")
MAC_AGENT_PORT = int(os.getenv("MAC_AGENT_PORT", "9900"))
MAC_AGENT_WORKSPACE = os.getenv(
    "MAC_AGENT_WORKSPACE",
    "/Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2",
)

DATA_DIR = os.path.join(MAC_AGENT_WORKSPACE, "data")
AUDIT_LOG = os.path.join(DATA_DIR, "mac_agent_audit.jsonl")
ALIVE_FILE = os.path.join(DATA_DIR, "mac_agent_alive.json")

_start_time = time.time()
logger = logging.getLogger("nate-mac-agent")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

# ── Security: Command Allowlist ──

ALLOWED_COMMAND_PREFIXES = [
    "python3", "python",
    "flutter", "dart",
    "git",
    "ls", "cat", "head", "tail", "wc", "grep", "rg", "find",
    "curl", "wget",
    "docker", "docker-compose",
    "pip", "pip3", "npm", "npx", "node",
    "cd", "pwd", "echo", "which", "env",
    "xcodebuild", "xcrun",
    "open",
    "brew",
    "scp", "rsync",
    "pytest", "mypy", "flake8", "black",
    "launchctl",
    "mkdir", "cp", "mv", "touch",
    "sleep",
]

SHELL_METACHARACTERS = set(";|&$`\\()")

RED_ZONE_PATHS = [
    "/etc/", "/private/etc/", "/System/", "/Library/", "/private/var/",
    os.path.expanduser("~/.ssh/id_"),
    os.path.expanduser("~/.gnupg/"),
    "/var/root/",
]

RED_ZONE_FILENAMES = [".env", "credentials.json", "key.properties", ".keystore", ".jks"]

EXEC_TIMEOUT_MAX = 600

# ── Security: Validation ──


def _validate_command(command: str) -> list[str]:
    """Validate command against allowlist and return parsed token list (shell=False)."""
    if any(c in command for c in SHELL_METACHARACTERS):
        raise HTTPException(403, f"Shell metacharacters are not permitted: {command!r}")

    try:
        tokens = shlex.split(command)
    except ValueError as e:
        raise HTTPException(400, f"Invalid command syntax: {e}")

    if not tokens:
        raise HTTPException(400, "Empty command")

    first_token = os.path.basename(tokens[0])
    if not any(first_token == prefix or first_token.startswith(prefix) for prefix in ALLOWED_COMMAND_PREFIXES):
        raise HTTPException(403, f"Command not permitted: {first_token}")

    return tokens


def _check_red_zone(path: str) -> None:
    """Reject file operations on sensitive paths."""
    resolved = os.path.realpath(os.path.expanduser(path))
    for rz in RED_ZONE_PATHS:
        if resolved.startswith(os.path.expanduser(rz)):
            raise HTTPException(403, f"Red-zone path: {path}")
    basename = os.path.basename(resolved)
    for rz_name in RED_ZONE_FILENAMES:
        if basename == rz_name or basename.endswith(rz_name):
            raise HTTPException(403, f"Red-zone file: {basename}")


# ── Workspace Mutex ──

_workspace_locks: dict[str, asyncio.Lock] = {}


def _get_workspace_lock(cwd: str) -> asyncio.Lock:
    canonical = os.path.realpath(cwd)
    if canonical not in _workspace_locks:
        _workspace_locks[canonical] = asyncio.Lock()
    return _workspace_locks[canonical]


_current_lock_holder: dict[str, str] = {}

# ── Audit Logging ──


async def _audit_log(action: str, detail: dict, caller_ip: str = "127.0.0.1"):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "caller_ip": caller_ip,
        **detail,
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        async with aiofiles.open(AUDIT_LOG, "a") as f:
            await f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.warning("Audit log write failed: %s", e)


# ── Process Management ──

_managed_pids: dict[str, Optional[int]] = {}
_restart_counts: dict[str, int] = {}


def _check_process_running(name: str) -> bool:
    """Check if a process with the given name is running via psutil."""
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if name in cmdline:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def _check_heartbeat_freshness(heartbeat_path: str, max_age_s: int = 600) -> bool:
    full_path = os.path.join(MAC_AGENT_WORKSPACE, heartbeat_path)
    if not os.path.exists(full_path):
        return False
    age = time.time() - os.path.getmtime(full_path)
    return age < max_age_s


# blue_harvester disabled 2026-05-22: Ollama 14B filter pegs CPU/GPU and drains Mac battery.
# Re-enable: restore entry with restart_policy "manual" and POST /process/manage start.
MANAGED_PROCESSES: dict[str, dict] = {}


def _check_system_cloudflared() -> bool:
    """Check if the system cloudflared LaunchDaemon is running (managed by macOS, not this agent)."""
    import subprocess
    try:
        result = subprocess.run(
            ["pgrep", "-x", "cloudflared"],
            capture_output=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        pass
    try:
        result = subprocess.run(
            ["launchctl", "list", "com.cloudflare.cloudflared"],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0 and '"PID"' in result.stdout
    except Exception:
        return False


def _get_process_status(name: str) -> dict:
    config = MANAGED_PROCESSES.get(name, {})
    pid = _managed_pids.get(name)
    running = False
    if pid:
        try:
            p = psutil.Process(pid)
            running = p.is_running() and p.status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            running = False

    if not running and name == "cloudflared":
        running = _check_process_running("cloudflared")

    return {
        "name": name,
        "pid": pid,
        "running": running,
        "restart_count": _restart_counts.get(name, 0),
        "restart_policy": config.get("restart_policy", "manual"),
    }


async def _start_managed_process(name: str) -> dict:
    config = MANAGED_PROCESSES.get(name)
    if not config:
        raise HTTPException(404, f"Unknown managed process: {name}")

    old_pid = _managed_pids.get(name)
    if old_pid:
        try:
            os.kill(old_pid, signal.SIGTERM)
            await asyncio.sleep(2)
        except (ProcessLookupError, PermissionError):
            pass

    proc = await asyncio.create_subprocess_exec(
        *config["command"],
        cwd=config["cwd"],
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )
    _managed_pids[name] = proc.pid
    logger.info("Started %s with PID %d", name, proc.pid)
    return {"status": "ok", "process": name, "pid": proc.pid}


async def _stop_managed_process(name: str) -> dict:
    pid = _managed_pids.get(name)
    if not pid:
        return {"status": "ok", "process": name, "message": "not running"}
    try:
        os.kill(pid, signal.SIGTERM)
        await asyncio.sleep(2)
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    except ProcessLookupError:
        pass
    _managed_pids[name] = None
    return {"status": "ok", "process": name, "message": "stopped"}


# ── Watchdog Coroutine ──

async def _watchdog_for_process(name: str, config: dict):
    """Per-process watchdog that checks health and auto-restarts on failure."""
    interval = config.get("health_check_interval_s", 300)
    while True:
        await asyncio.sleep(interval)

        health_fn = config.get("health_check")
        if health_fn and health_fn():
            _restart_counts[name] = 0
            continue

        max_restarts = config.get("max_auto_restarts", 3)
        count = _restart_counts.get(name, 0)
        if count >= max_restarts:
            logger.warning("%s: auto-restart exhausted (%d/%d), manual intervention needed",
                           name, count, max_restarts)
            continue

        logger.info("Watchdog: %s unhealthy, restarting (attempt %d/%d)", name, count + 1, max_restarts)
        try:
            await _start_managed_process(name)
            _restart_counts[name] = count + 1
        except Exception as e:
            logger.error("Watchdog: failed to restart %s: %s", name, e)
            _restart_counts[name] = count + 1

        cooldown = config.get("cooldown_s", 60)
        await asyncio.sleep(cooldown)


async def _watchdog_loop():
    """Spawn per-process watchdog tasks concurrently."""
    tasks = []
    for name, config in MANAGED_PROCESSES.items():
        if config.get("restart_policy") != "on-failure":
            continue
        tasks.append(asyncio.create_task(_watchdog_for_process(name, config)))
    if tasks:
        await asyncio.gather(*tasks)


# ── Alive File Writer ──

async def _write_alive_file():
    """Write local health file every 60s for tunnel-down resilience."""
    while True:
        payload = {
            "agent": "nate-mac-agent",
            "status": "ok",
            "uptime_s": round(time.time() - _start_time, 1),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "managed_processes": {name: _get_process_status(name) for name in MANAGED_PROCESSES},
            "tunnel_healthy": _check_system_cloudflared(),
        }
        os.makedirs(DATA_DIR, exist_ok=True)
        try:
            async with aiofiles.open(ALIVE_FILE, "w") as f:
                await f.write(json.dumps(payload, indent=2))
        except Exception as e:
            logger.warning("Alive file write failed: %s", e)
        await asyncio.sleep(60)


# ── FastAPI App ──

app = FastAPI(title="nate-mac-agent", version="1.0.0")
security = HTTPBearer()

_ALLOWED_CLIENT_HOSTS = {"127.0.0.1", "::1", "localhost"}


@app.middleware("http")
async def validate_request_origin(request, call_next):
    """Defense-in-depth: only accept connections from localhost or Cloudflare tunnel."""
    client_host = request.client.host if request.client else None
    is_cloudflare = bool(request.headers.get("cf-ray"))
    if client_host is not None and client_host not in _ALLOWED_CLIENT_HOSTS and not is_cloudflare:
        logger.warning("Rejected request from non-local origin: %s", client_host)
        return JSONResponse(status_code=403, content={"detail": "Forbidden: non-local origin"})
    return await call_next(request)


async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not MAC_AGENT_TOKEN:
        raise HTTPException(500, "MAC_AGENT_TOKEN not configured")
    if credentials.credentials != MAC_AGENT_TOKEN:
        raise HTTPException(403, "Invalid token")
    return credentials.credentials


# ── Request Models ──

class ExecRequest(BaseModel):
    command: str
    cwd: Optional[str] = None
    timeout_seconds: int = 120


class FileReadRequest(BaseModel):
    path: str
    offset: Optional[int] = None
    limit: Optional[int] = None


class FileWriteRequest(BaseModel):
    path: str
    content: Optional[str] = None
    old_string: Optional[str] = None
    new_string: Optional[str] = None


class FileDeleteRequest(BaseModel):
    path: str


class GitRequest(BaseModel):
    operation: str  # status, diff, add, commit, push, log
    args: Optional[list[str]] = None
    message: Optional[str] = None
    cwd: Optional[str] = None


class BuildRequest(BaseModel):
    build_type: str  # flutter_build, dart_analyze, python_lint
    cwd: Optional[str] = None
    args: Optional[list[str]] = None
    timeout_seconds: int = 300


class ProcessManageRequest(BaseModel):
    action: str  # start, stop, restart, status
    process: str


class LintRequest(BaseModel):
    paths: list[str] = []


# ── Endpoints ──

@app.get("/health")
async def health():
    """Intentionally unauthenticated — bound to 127.0.0.1, only reachable through
    Cloudflare VPC tunnel with Access Policy.  Allows health monitors (Cloudflare,
    load balancer probes) to check liveness without token exchange."""
    alive_age = None
    if os.path.exists(ALIVE_FILE):
        alive_age = round(time.time() - os.path.getmtime(ALIVE_FILE), 1)
    return {
        "status": "ok",
        "agent": "nate-mac-agent",
        "uptime_s": round(time.time() - _start_time, 1),
        "workspace": MAC_AGENT_WORKSPACE,
        "tunnel_healthy": _check_system_cloudflared(),
        "alive_file_age_s": alive_age,
        "managed_processes": {n: _get_process_status(n) for n in MANAGED_PROCESSES},
    }


@app.get("/heartbeat", dependencies=[Depends(verify_token)])
async def heartbeat():
    lock_status = {}
    for cwd, lock in _workspace_locks.items():
        lock_status[cwd] = {
            "locked": lock.locked(),
            "holder": _current_lock_holder.get(cwd),
        }
    return {
        "agent": "nate-mac-agent",
        "status": "ok",
        "uptime_s": round(time.time() - _start_time, 1),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "workspace": MAC_AGENT_WORKSPACE,
        "tunnel_healthy": _check_system_cloudflared(),
        "managed_processes": {n: _get_process_status(n) for n in MANAGED_PROCESSES},
        "workspace_locks": lock_status,
        "system": {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage(MAC_AGENT_WORKSPACE).percent,
        },
    }


@app.post("/exec", dependencies=[Depends(verify_token)])
async def exec_command(req: ExecRequest, request: Request):
    tokens = _validate_command(req.command)
    effective_timeout = min(req.timeout_seconds, EXEC_TIMEOUT_MAX)
    cwd = req.cwd or MAC_AGENT_WORKSPACE

    lock = _get_workspace_lock(cwd)
    async with lock:
        _current_lock_holder[os.path.realpath(cwd)] = req.command
        try:
            await _audit_log("exec", {"command": req.command, "cwd": cwd, "timeout": effective_timeout},
                             request.client.host if request.client else "unknown")

            proc = await asyncio.create_subprocess_exec(
                *tokens,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                start_new_session=True,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=effective_timeout)
                return {
                    "status": "ok",
                    "exit_code": proc.returncode,
                    "stdout": stdout.decode(errors="replace")[-50000:],
                    "stderr": stderr.decode(errors="replace")[-10000:],
                }
            except asyncio.TimeoutError:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                partial_stdout = b""
                partial_stderr = b""
                try:
                    partial_stdout, partial_stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
                except Exception:
                    pass
                return {
                    "status": "error",
                    "error": f"Command timed out after {effective_timeout}s",
                    "error_code": "TIMEOUT",
                    "partial_stdout": partial_stdout.decode(errors="replace")[-50000:],
                    "partial_stderr": partial_stderr.decode(errors="replace")[-10000:],
                    "warning": "Process was killed. Check for lock files, partial writes, or uncommitted git state.",
                }
        finally:
            _current_lock_holder.pop(os.path.realpath(cwd), None)


@app.post("/file/read", dependencies=[Depends(verify_token)])
async def file_read(req: FileReadRequest):
    path = os.path.expanduser(req.path)
    if not os.path.isabs(path):
        path = os.path.join(MAC_AGENT_WORKSPACE, path)
    _check_red_zone(path)

    if not os.path.exists(path):
        return {"status": "error", "error": f"File not found: {path}", "error_code": "FILE_NOT_FOUND"}

    try:
        async with aiofiles.open(path, "r", errors="replace") as f:
            lines = await f.readlines()
    except Exception as e:
        return {"status": "error", "error": str(e), "error_code": "READ_ERROR"}

    if req.offset is not None:
        start = max(0, req.offset - 1) if req.offset > 0 else max(0, len(lines) + req.offset)
        end = start + (req.limit or len(lines))
        lines = lines[start:end]

    numbered = []
    base = (req.offset or 1) if req.offset and req.offset > 0 else 1
    for i, line in enumerate(lines):
        numbered.append(f"{base + i:6d}|{line.rstrip()}")

    return {"status": "ok", "content": "\n".join(numbered), "total_lines": len(lines)}


@app.post("/file/write", dependencies=[Depends(verify_token)])
async def file_write(req: FileWriteRequest, request: Request):
    path = os.path.expanduser(req.path)
    if not os.path.isabs(path):
        path = os.path.join(MAC_AGENT_WORKSPACE, path)
    _check_red_zone(path)

    lock = _get_workspace_lock(os.path.dirname(path))
    async with lock:
        _current_lock_holder[os.path.realpath(os.path.dirname(path))] = f"file/write {path}"
        try:
            await _audit_log("file_write", {"path": path}, request.client.host if request.client else "unknown")

            if req.old_string is not None and req.new_string is not None:
                if not os.path.exists(path):
                    return {"status": "error", "error": f"File not found for str_replace: {path}"}
                async with aiofiles.open(path, "r") as f:
                    content = await f.read()
                if req.old_string not in content:
                    return {"status": "error", "error": "old_string not found in file"}
                count = content.count(req.old_string)
                if count > 1:
                    return {"status": "error", "error": f"old_string appears {count} times — must be unique"}
                content = content.replace(req.old_string, req.new_string, 1)
                async with aiofiles.open(path, "w") as f:
                    await f.write(content)
                return {"status": "ok", "action": "str_replace", "path": path}

            elif req.content is not None:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                async with aiofiles.open(path, "w") as f:
                    await f.write(req.content)
                return {"status": "ok", "action": "write", "path": path}

            return {"status": "error", "error": "Provide content (full write) or old_string+new_string (str_replace)"}
        finally:
            _current_lock_holder.pop(os.path.realpath(os.path.dirname(path)), None)


@app.post("/file/delete", dependencies=[Depends(verify_token)])
async def file_delete(req: FileDeleteRequest, request: Request):
    path = os.path.expanduser(req.path)
    if not os.path.isabs(path):
        path = os.path.join(MAC_AGENT_WORKSPACE, path)
    _check_red_zone(path)

    lock = _get_workspace_lock(os.path.dirname(path))
    async with lock:
        await _audit_log("file_delete", {"path": path}, request.client.host if request.client else "unknown")
        if not os.path.exists(path):
            return {"status": "error", "error": f"File not found: {path}", "error_code": "FILE_NOT_FOUND"}
        os.remove(path)
        return {"status": "ok", "action": "deleted", "path": path}


@app.post("/lint", dependencies=[Depends(verify_token)])
async def lint_paths(req: LintRequest, request: Request):
    """Run lightweight syntax/lint checks on workspace paths (read_lints mapping)."""
    await _audit_log("lint", {"paths": (req.paths or [])[:20]}, request.client.host if request.client else "unknown")
    diagnostics = []
    for raw in (req.paths or [])[:20]:
        path = os.path.expanduser(raw)
        if not os.path.isabs(path):
            path = os.path.join(MAC_AGENT_WORKSPACE, path)
        try:
            _check_red_zone(path)
        except HTTPException as he:
            diagnostics.append({"path": raw, "errors": [{"message": str(he.detail), "severity": "error"}], "clean": False})
            continue
        if not os.path.isfile(path):
            diagnostics.append({"path": raw, "errors": [{"message": "File not found", "severity": "error"}], "clean": False})
            continue
        errors = []
        ext = Path(path).suffix.lower()
        if ext == ".py":
            proc = await asyncio.create_subprocess_exec(
                "python3", "-m", "py_compile", path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            except asyncio.TimeoutError:
                errors.append({"message": "py_compile timed out", "severity": "error"})
                proc.kill()
            else:
                if proc.returncode != 0:
                    for line in (stderr.decode(errors="replace") or "").strip().splitlines()[:20]:
                        errors.append({"message": line.strip(), "severity": "error"})
        elif ext == ".dart":
            proc = await asyncio.create_subprocess_exec(
                "dart", "analyze", path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=MAC_AGENT_WORKSPACE,
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            except asyncio.TimeoutError:
                errors.append({"message": "dart analyze timed out", "severity": "error"})
                proc.kill()
            else:
                if proc.returncode != 0:
                    for line in (stdout.decode(errors="replace") or "").strip().splitlines()[:20]:
                        if line.strip():
                            errors.append({"message": line.strip(), "severity": "error"})
        else:
            errors.append({"message": f"No lint runner for extension {ext or '(none)'}", "severity": "info"})
        diagnostics.append({"path": raw, "errors": errors, "clean": len(errors) == 0})

    return {
        "status": "ok",
        "diagnostics": diagnostics,
        "result": diagnostics,
        "total_files": len(diagnostics),
        "files_with_errors": sum(1 for d in diagnostics if d.get("errors")),
    }


@app.post("/git", dependencies=[Depends(verify_token)])
async def git_operation(req: GitRequest, request: Request):
    cwd = req.cwd or MAC_AGENT_WORKSPACE
    allowed_ops = {"status", "diff", "add", "commit", "push", "log", "pull", "stash", "branch", "checkout"}
    if req.operation not in allowed_ops:
        raise HTTPException(403, f"Git operation not permitted: {req.operation}")

    cmd_parts = ["git", req.operation]
    if req.operation == "commit" and req.message:
        cmd_parts.extend(["-m", req.message])
    if req.args:
        cmd_parts.extend(req.args)

    lock = _get_workspace_lock(cwd)
    async with lock:
        _current_lock_holder[os.path.realpath(cwd)] = f"git {req.operation}"
        try:
            await _audit_log("git", {"operation": req.operation, "cwd": cwd},
                             request.client.host if request.client else "unknown")

            proc = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                start_new_session=True,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
                return {
                    "status": "ok",
                    "exit_code": proc.returncode,
                    "stdout": stdout.decode(errors="replace")[-50000:],
                    "stderr": stderr.decode(errors="replace")[-10000:],
                }
            except asyncio.TimeoutError:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                return {"status": "error", "error": "Git operation timed out after 120s", "error_code": "TIMEOUT"}
        finally:
            _current_lock_holder.pop(os.path.realpath(cwd), None)


@app.post("/build", dependencies=[Depends(verify_token)])
async def build(req: BuildRequest, request: Request):
    cwd = req.cwd or MAC_AGENT_WORKSPACE
    effective_timeout = min(req.timeout_seconds, EXEC_TIMEOUT_MAX)

    build_commands = {
        "flutter_build": ["flutter", "build", "web", "--release"],
        "flutter_build_ios": ["flutter", "build", "ios", "--release", "--no-codesign"],
        "flutter_build_apk": ["flutter", "build", "apk", "--release"],
        "dart_analyze": ["dart", "analyze"],
        "python_lint": ["python3", "-m", "flake8"],
        "flutter_test": ["flutter", "test"],
        "pytest": ["python3", "-m", "pytest", "-v"],
    }

    cmd = build_commands.get(req.build_type)
    if not cmd:
        raise HTTPException(400, f"Unknown build type: {req.build_type}. Available: {list(build_commands.keys())}")

    if req.args:
        cmd.extend(req.args)

    lock = _get_workspace_lock(cwd)
    async with lock:
        _current_lock_holder[os.path.realpath(cwd)] = f"build {req.build_type}"
        try:
            await _audit_log("build", {"build_type": req.build_type, "cwd": cwd},
                             request.client.host if request.client else "unknown")

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                start_new_session=True,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=effective_timeout)
                return {
                    "status": "ok",
                    "exit_code": proc.returncode,
                    "build_type": req.build_type,
                    "stdout": stdout.decode(errors="replace")[-50000:],
                    "stderr": stderr.decode(errors="replace")[-10000:],
                }
            except asyncio.TimeoutError:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                partial_stdout = b""
                partial_stderr = b""
                try:
                    partial_stdout, partial_stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
                except Exception:
                    pass
                return {
                    "status": "error",
                    "error": f"Build timed out after {effective_timeout}s",
                    "error_code": "TIMEOUT",
                    "build_type": req.build_type,
                    "partial_stdout": partial_stdout.decode(errors="replace")[-50000:],
                    "partial_stderr": partial_stderr.decode(errors="replace")[-10000:],
                    "warning": "Build process was killed. Partial build artifacts may exist.",
                }
        finally:
            _current_lock_holder.pop(os.path.realpath(cwd), None)


@app.post("/process/manage", dependencies=[Depends(verify_token)])
async def process_manage(req: ProcessManageRequest, request: Request):
    await _audit_log("process_manage", {"action": req.action, "process": req.process},
                     request.client.host if request.client else "unknown")

    if req.action == "status":
        if req.process == "all":
            return {"status": "ok", "processes": {n: _get_process_status(n) for n in MANAGED_PROCESSES}}
        return {"status": "ok", **_get_process_status(req.process)}

    if req.process not in MANAGED_PROCESSES:
        raise HTTPException(404, f"Unknown managed process: {req.process}")

    if req.action == "start":
        result = await _start_managed_process(req.process)
        return result
    elif req.action == "stop":
        result = await _stop_managed_process(req.process)
        return result
    elif req.action == "restart":
        await _stop_managed_process(req.process)
        await asyncio.sleep(2)
        result = await _start_managed_process(req.process)
        return result
    else:
        raise HTTPException(400, f"Unknown action: {req.action}. Use start, stop, restart, or status.")


# ── Dual-COO Mac Queen heartbeat ──

QUEEN_BEAT_INTERVAL_S = int(os.getenv("MAC_QUEEN_BEAT_INTERVAL_S", "60"))


async def _dual_coo_queen_beat_loop():
    """Background Mac Queen Redis heartbeat (independent of CLI chat sessions).

    Writes beat_queen('mac') when REDIS_URL is reachable. Cloud also probes
    MAC_AGENT_URL /health and can write the same beat — dual path.
    """
    await asyncio.sleep(5)
    while True:
        try:
            # Prefer importing from workspace backend package when available
            sys.path.insert(0, os.path.join(MAC_AGENT_WORKSPACE, "backend"))
            from app.websocket.cli_dual_coo import beat_queen, dual_coo_enabled

            if dual_coo_enabled():
                ok = beat_queen(
                    "mac",
                    meta={
                        "via": "mac_agent_loop",
                        "uptime_s": round(time.time() - _start_time, 1),
                    },
                )
                if ok:
                    logger.debug("Dual-COO Mac Queen beat ok")
                else:
                    logger.debug("Dual-COO Mac Queen beat skipped (redis?)")
        except Exception as e:
            logger.debug("Dual-COO Mac Queen beat: %s", e)
        await asyncio.sleep(max(30, QUEEN_BEAT_INTERVAL_S))


# ── Lifecycle ──

@app.on_event("startup")
async def startup():
    os.makedirs(DATA_DIR, exist_ok=True)
    asyncio.create_task(_watchdog_loop())
    asyncio.create_task(_write_alive_file())
    asyncio.create_task(_dual_coo_queen_beat_loop())
    logger.info("nate-mac-agent started on 127.0.0.1:%d", MAC_AGENT_PORT)
    logger.info("Workspace: %s", MAC_AGENT_WORKSPACE)
    logger.info("Dual-COO Mac Queen beat loop interval=%ss", QUEEN_BEAT_INTERVAL_S)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=MAC_AGENT_PORT)

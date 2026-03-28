"""
CLI Tool Functions for the Command Terminal.

Phase 1: Read-only tools — read_file, search_code, list_directory.
Phase 2: Write tools (CLI-Mac only) — write_file, inject_log, debug_cleanup.
Phase 4: Data query tools (CLI-Cloud ADMIN only) — query_sessions, query_coherence_data, query_user_profile.
Phase 5: Cursor-parity tools — str_replace, grep, glob, shell, read_lints, delete_file.
Auth-scoped execute_tool dispatcher with per-tool timeouts and path traversal security.
"""

import asyncio
import fnmatch
import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import app.websocket.tools as _ln_ws_tools
    TOOL_TIMEOUTS = {
        **{
            "read_file": 5,
            "search_code": 10,
            "list_directory": 3,
            "write_file": 5,
            "str_replace": 5,
            "delete_file": 3,
            "inject_log": 5,
            "debug_cleanup": 10,
            "grep": 15,
            "glob": 5,
            "shell": 120,
            "read_lints": 20,
            "web_fetch": 15,
            "web_search_local": 20,
            "todo_write": 2,
            "switch_mode": 1,
            "provider_stats": 5,
            "query_sessions": 10,
            "query_coherence_data": 10,
            "query_user_profile": 5,
            "build_start": 30,
            "build_test": 90,
            "build_promote": 10,
            "build_rollback": 10,
            "build_status": 5,
        },
        **_ln_ws_tools.TOOL_TIMEOUTS,
    }
    _LN_TOOL_NAMES = _ln_ws_tools.LN_TOOL_NAMES
    _wrap_ln_tool_def = _ln_ws_tools.wrap_tool_def_for_ollama
    _LN_TOOLS_AVAILABLE = True
except (ImportError, AttributeError) as _ln_imp_err:
    logger.warning("app.websocket.tools not fully available: %s", _ln_imp_err)
    _LN_TOOL_NAMES = frozenset()
    _LN_TOOLS_AVAILABLE = False
    TOOL_TIMEOUTS = {
        "read_file": 5,
        "search_code": 10,
        "list_directory": 3,
        "write_file": 5,
        "str_replace": 5,
        "delete_file": 3,
        "inject_log": 5,
        "debug_cleanup": 10,
        "grep": 15,
        "glob": 5,
        "shell": 120,
        "read_lints": 20,
        "web_fetch": 15,
        "web_search_local": 20,
        "todo_write": 2,
        "switch_mode": 1,
        "provider_stats": 5,
        "query_sessions": 10,
        "query_coherence_data": 10,
        "query_user_profile": 5,
        "build_start": 30,
        "build_test": 90,
        "build_promote": 10,
        "build_rollback": 10,
        "build_status": 5,
    }

    def _wrap_ln_tool_def(defn: dict) -> dict:  # type: ignore[misc]
        return {
            "type": "function",
            "function": {
                "name": defn.get("name", "unknown"),
                "description": defn.get("description", ""),
                "parameters": defn.get("parameters", {"type": "object", "properties": {}}),
            },
        }

_PROJECT_ROOT_DOCKER = "/app"
_PROJECT_ROOT_LOCAL = os.environ.get("CLI_PROJECT_ROOT", os.getcwd())

TRUNCATION_LIMITS = {
    ("mac", "ask"): 12000,
    ("mac", "plan"): 12000,
    ("mac", "debug"): 12000,
    ("mac", "ln_fab"): 20000,
    ("cloud", "ask"): 12000,
    ("cloud", "plan"): 12000,
    ("cloud", "debug"): 12000,
    ("cloud", "ln_fab"): 20000,
}

_WRITE_TOOLS = {"write_file", "str_replace", "delete_file", "inject_log", "debug_cleanup", "build_start", "build_promote", "build_rollback"}
_SHELL_TOOLS = {"shell"}
_LINT_TOOLS = {"read_lints"}
_NET_TOOLS = {"web_fetch", "web_search_local"}
_SESSION_TOOLS = {"todo_write", "switch_mode"}

# Mac agent forwarding — tools that should execute on the Mac when cli_type == "mac"
_MAC_AGENT_TOOLS = _WRITE_TOOLS | _SHELL_TOOLS | _LINT_TOOLS | _NET_TOOLS | {"read_file", "list_directory", "grep", "glob", "build_flutter", "build_check", "process_manage", "ssh_deploy"}
_MAC_AGENT_URL = os.getenv("MAC_AGENT_URL", "")
_MAC_AGENT_TOKEN = os.getenv("MAC_AGENT_TOKEN", "")
MAC_AGENT_HTTP_TIMEOUT = 660  # 600s agent max + 60s network buffer


async def _forward_to_mac_agent(endpoint: str, payload: dict) -> dict:
    """Forward a tool call to the Mac agent via HTTP."""
    if not _MAC_AGENT_URL:
        return {"status": "error", "error": "Mac agent not configured (MAC_AGENT_URL empty). Start the Mac agent locally or switch to CLI-Cloud.", "error_code": "MAC_AGENT_OFFLINE"}
    try:
        import aiohttp
        url = f"{_MAC_AGENT_URL.rstrip('/')}{endpoint}"
        timeout = aiohttp.ClientTimeout(total=MAC_AGENT_HTTP_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            headers = {"Authorization": f"Bearer {_MAC_AGENT_TOKEN}"}
            async with session.post(url, json=payload, headers=headers) as resp:
                return await resp.json()
    except Exception as e:
        return {"status": "error", "error": f"Mac agent unreachable: {e}", "error_code": "MAC_AGENT_OFFLINE"}


def _map_tool_to_mac_agent(name: str, args: Dict[str, Any]) -> tuple[str, dict]:
    """Map a CLI tool name + args to a Mac agent endpoint + payload."""
    if name == "shell":
        return "/exec", {"command": args.get("command", ""), "cwd": args.get("cwd"), "timeout_seconds": args.get("timeout", 120)}
    if name == "read_file":
        return "/file/read", {"path": args.get("path", ""), "offset": args.get("start_line"), "limit": args.get("end_line")}
    if name == "write_file":
        return "/file/write", {"path": args.get("path", ""), "content": args.get("content", "")}
    if name == "str_replace":
        return "/file/write", {"path": args.get("path", ""), "old_string": args.get("old_string"), "new_string": args.get("new_string")}
    if name == "delete_file":
        return "/file/delete", {"path": args.get("path", "")}
    if name in ("build_start", "build_flutter", "build_check"):
        return "/build", {"build_type": args.get("build_type", "flutter_build"), "cwd": args.get("cwd"), "timeout_seconds": args.get("timeout", 300)}
    if name == "process_manage":
        return "/process/manage", {"action": args.get("action", "status"), "process": args.get("process", "all")}
    if name in ("grep", "glob", "list_directory"):
        cmd = "rg" if name == "grep" else ("find" if name == "glob" else "ls")
        pattern = args.get("pattern", "")
        path = args.get("path", ".")
        if name == "grep":
            return "/exec", {"command": f"rg {pattern} {path}", "timeout_seconds": 15}
        if name == "glob":
            return "/exec", {"command": f"find {path} -name {pattern}", "timeout_seconds": 10}
        return "/exec", {"command": f"ls -la {path}", "timeout_seconds": 5}
    if name == "ssh_deploy":
        return "__ssh_deploy__", args
    return "/exec", {"command": f"echo 'Unmapped tool: {name}'", "timeout_seconds": 5}


async def _forward_ssh_deploy_to_mac_agent(args: Dict[str, Any]) -> Dict[str, Any]:
    """Decompose an ssh_deploy operation into individual /exec calls on the Mac agent."""
    try:
        from app.websocket.tools.ssh_write_tools import WRITE_OPERATIONS
    except ImportError:
        return {"status": "error", "error": "ssh_write_tools not available", "error_code": "IMPORT_ERROR"}

    op_name = args.get("operation", "")
    op = WRITE_OPERATIONS.get(op_name)
    if not op:
        return {"status": "error", "error": f"Unknown deploy operation: {op_name}", "error_code": "UNKNOWN_OP"}

    server_alias = args.get("server", "primary")
    server_map = {"primary": "root@68.183.168.75", "clone": "root@159.65.108.25", "hetzner": "root@37.27.244.80"}
    server_host = server_map.get(server_alias, server_alias)

    results = []
    for i, cmd in enumerate(op.commands):
        resolved_cmd = cmd.replace("{server}", server_host)
        if args.get("migration_file"):
            resolved_cmd = resolved_cmd.replace("{migration_file}", args["migration_file"])
        result = await _forward_to_mac_agent("/exec", {"command": resolved_cmd, "timeout_seconds": 300})
        results.append({"step": i + 1, "phase": "execute", "command": resolved_cmd[:120], "result": result})
        if result.get("status") == "error" or (result.get("exit_code") or 0) != 0:
            for j, rb_cmd in enumerate(op.rollback_commands):
                rb_result = await _forward_to_mac_agent("/exec", {"command": rb_cmd.replace("{server}", server_host), "timeout_seconds": 120})
                results.append({"step": j + 1, "phase": "rollback", "result": rb_result})
            return {"status": "error", "operation": op_name, "error": f"Command failed at step {i + 1}", "steps": results}

    for i, vcmd in enumerate(op.verify_commands):
        v_result = await _forward_to_mac_agent("/exec", {"command": vcmd.replace("{server}", server_host), "timeout_seconds": 60})
        results.append({"step": i + 1, "phase": "verify", "command": vcmd[:120], "result": v_result})

    return {"status": "ok", "operation": op_name, "steps": results}


_FILE_TYPE_EXTENSIONS = {
    "py": ["*.py"],
    "js": ["*.js", "*.mjs", "*.cjs"],
    "ts": ["*.ts", "*.tsx"],
    "dart": ["*.dart"],
    "sql": ["*.sql"],
    "html": ["*.html", "*.htm"],
    "css": ["*.css", "*.scss", "*.sass"],
    "yaml": ["*.yaml", "*.yml"],
    "json": ["*.json"],
    "md": ["*.md", "*.mdx"],
    "rs": ["*.rs"],
    "go": ["*.go"],
    "java": ["*.java"],
    "rb": ["*.rb"],
    "sh": ["*.sh", "*.bash"],
    "toml": ["*.toml"],
    "xml": ["*.xml"],
}

_SKIP_DIRS = {
    "node_modules", "__pycache__", ".git", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", "build", ".dart_tool",
    "CSL - Cursor",
}

# Error codes for LLM self-correction (Gap Audit 3B)
_ERROR_FILE_NOT_FOUND = "FILE_NOT_FOUND"
_ERROR_BINARY_FILE = "BINARY_FILE"
_ERROR_PATH_TRAVERSAL = "PATH_TRAVERSAL"
_ERROR_PERMISSION_DENIED = "PERMISSION_DENIED"
_ERROR_TIMEOUT = "TIMEOUT"
_ERROR_GREP_NO_MATCH = "GREP_NO_MATCH"
_ERROR_SHELL_NONZERO = "SHELL_NONZERO"
_ERROR_WRITE_CONFLICT = "WRITE_CONFLICT"
_ERROR_TRUNCATED = "TRUNCATED"
_ERROR_OTHER = "OTHER"

_BINARY_EXTENSIONS = {
    ".pyc", ".pyo", ".so", ".dll", ".exe", ".bin", ".class",
    ".jar", ".zip", ".gz", ".tar", ".png", ".jpg", ".jpeg",
    ".gif", ".ico", ".woff", ".woff2", ".ttf", ".eot", ".pdf",
    ".mp3", ".mp4", ".wav", ".mov", ".aab", ".apk", ".ipa",
}

_READ_TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the project. Returns numbered lines. Max 500 lines per call; use start_line/end_line for larger files. Negative start_line reads from the end (e.g., -20 = last 20 lines).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path from project root"},
                    "start_line": {"type": "integer", "description": "1-indexed start line. Negative values count from end (-1 = last line, -20 = last 20 lines)."},
                    "end_line": {"type": "integer", "description": "1-indexed end line (optional)"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search for a regex pattern across project files. Returns matching lines with file paths and line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern to search for"},
                    "path": {"type": "string", "description": "Subdirectory to limit search (optional)"},
                    "glob": {"type": "string", "description": "File glob filter e.g. '*.py' (optional)"},
                    "max_results": {"type": "integer", "description": "Max matches to return (default 20)"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and directories at a given path with optional glob filter.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative directory path (default: project root)"},
                    "pattern": {"type": "string", "description": "Glob filter e.g. '*.py' (optional)"},
                },
                "required": [],
            },
        },
    },
]

_WRITE_TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file. Creates parent directories if needed. CLI-Mac only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path from project root"},
                    "content": {"type": "string", "description": "Full file content to write"},
                    "create_only": {"type": "boolean", "description": "If true, fail if file already exists (default false)"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inject_log",
            "description": "Inject a logging statement at a specific line in a file. Snapshots the original for cleanup. CLI-Mac DEBUG mode only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to the file"},
                    "line": {"type": "integer", "description": "1-indexed line number to insert BEFORE"},
                    "statement": {"type": "string", "description": "The logging statement to inject (e.g. print('>>> DEBUG: x =', x))"},
                },
                "required": ["path", "line", "statement"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "debug_cleanup",
            "description": "Revert all files modified by inject_log during this debug session. Restores original content from snapshots.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]

_PHASE5_TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "str_replace",
            "description": "Perform a surgical string replacement in a file. Replaces one exact occurrence of old_string with new_string. Much safer than rewriting the entire file. The old_string must be unique in the file — include enough context lines to ensure uniqueness.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path from project root"},
                    "old_string": {"type": "string", "description": "The exact text to find and replace (must be unique in the file)"},
                    "new_string": {"type": "string", "description": "The replacement text"},
                    "replace_all": {"type": "boolean", "description": "If true, replace ALL occurrences (default false)"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a file at the specified path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to the file to delete"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Fast regex search with context lines (like ripgrep). Supports multiple output modes, asymmetric context, multiline matching, and file-type filtering.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern to search for"},
                    "path": {"type": "string", "description": "File or directory to search in (default: project root)"},
                    "glob": {"type": "string", "description": "File glob filter, e.g. '*.py', '*.{ts,tsx}'"},
                    "context_lines": {"type": "integer", "description": "Symmetric context lines before+after (default 2). Overridden by -A/-B."},
                    "A": {"type": "integer", "description": "Lines to show AFTER each match (overrides context_lines)"},
                    "B": {"type": "integer", "description": "Lines to show BEFORE each match (overrides context_lines)"},
                    "max_results": {"type": "integer", "description": "Max matches to return (default 30)"},
                    "head_limit": {"type": "integer", "description": "Limit output: for content mode limits matches, for files_with_matches/count limits files"},
                    "offset": {"type": "integer", "description": "Skip first N results (for pagination)"},
                    "case_insensitive": {"type": "boolean", "description": "Case-insensitive search (default false)"},
                    "output_mode": {"type": "string", "description": "Output mode: 'content' (matching lines+context, default), 'files_with_matches' (file paths only), 'count' (match counts per file)"},
                    "multiline": {"type": "boolean", "description": "Enable multiline mode where . matches newlines and patterns can span lines (default false)"},
                    "type": {"type": "string", "description": "File type filter shorthand: 'py', 'js', 'ts', 'dart', 'sql', 'html', 'css', 'yaml', 'json', 'md', 'rs', 'go', 'java'"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "glob",
            "description": "Find files matching a glob pattern. Returns matching file paths sorted by modification time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern, e.g. '*.py', '**/test_*.py', 'backend/**/*.sql'"},
                    "target_directory": {"type": "string", "description": "Directory to search in (default: project root)"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shell",
            "description": "Execute a shell command. Use for git operations, running tests, package management, build commands. The shell is stateful — cwd and env persist between calls.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The shell command to execute"},
                    "working_directory": {"type": "string", "description": "Working directory (relative to project root, default: project root)"},
                    "block_until_ms": {"type": "integer", "description": "Max milliseconds to wait before backgrounding (default 30000). Set to 0 for immediate background. Use higher values for long builds."},
                    "description": {"type": "string", "description": "Short (5-10 word) description of what the command does"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_lints",
            "description": "Check files or directories for syntax and lint errors. Supports Python (.py), Dart (.dart), JavaScript/TypeScript (.js/.ts). If a directory is provided, checks all supported files within it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Array of file or directory paths to check for lint errors",
                    },
                },
                "required": ["paths"],
            },
        },
    },
]

_PHASE6_TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch content from a URL and return it as readable text. Use for reading documentation, API references, or web pages. Does not support authentication or binary content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The fully-formed URL to fetch"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search_local",
            "description": "Search the web via DuckDuckGo Lite. Use when you need current information, documentation, or answers from the web without Grok. Returns titles, URLs, and snippets. LN:Local only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "todo_write",
            "description": "Create or update a structured task list for the current session. Helps track progress on complex, multi-step tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string", "description": "Unique identifier for this TODO"},
                                "content": {"type": "string", "description": "Description of the task"},
                                "status": {"type": "string", "description": "pending | in_progress | completed | cancelled"},
                            },
                            "required": ["id", "content", "status"],
                        },
                        "description": "Array of TODO items to create or update",
                    },
                    "merge": {"type": "boolean", "description": "If true, merge with existing todos by id. If false, replace all (default false)."},
                },
                "required": ["todos"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "switch_mode",
            "description": "Recommend switching to a different CLI mode. Use when the current mode isn't optimal for the task (e.g., ASK mode when the user wants to implement, or LN-FAB mode when they need debugging).",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_mode": {"type": "string", "description": "Mode to switch to: 'ask', 'plan', 'ln_fab', or 'debug'"},
                    "explanation": {"type": "string", "description": "Brief explanation of why this mode is better for the current task"},
                },
                "required": ["target_mode", "explanation"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "provider_stats",
            "description": "Show inference provider utilization stats: calls by provider (count, %), total estimated cost, cost savings vs all-Grok/all-Azure baselines. Returns both current session and all-time stats from the JSONL log.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]

# --- Build System Tools (Blue-Green-Orange deployment) ---
_BUILD_TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "build_start",
            "description": (
                "Start a new versioned build. Backs up the current stable version, "
                "forks it to a new version directory. All subsequent file edits should "
                "target the working version. Bump level: 'patch' (default), 'minor', "
                "'major', or 'breaking'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "bump_level": {
                        "type": "string",
                        "description": "Version bump level: patch|minor|major|breaking (default: patch)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_test",
            "description": (
                "Run the 6 automated pre-promotion checks on the current working version: "
                "syntax, imports, bridge startup, tool smoke, crystal pipeline, migration safety. "
                "All must pass before Orange verification or promotion."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_promote",
            "description": (
                "Promote the current working version to live. Atomically swaps the live/ "
                "symlink. Only call after build_test passes. Specify cli='blue' (default) "
                "or cli='green'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cli": {
                        "type": "string",
                        "description": "Which CLI is promoting: blue|green (default: blue)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_rollback",
            "description": (
                "Roll back to a previous version. Swaps the live/ symlink to the last "
                "known good version (or a specific target). One command, instant."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target_version": {
                        "type": "string",
                        "description": "Specific version to roll back to (e.g. 'v1.0.0.0'). If omitted, rolls back to the previous promoted version.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_status",
            "description": (
                "Show current build status: stable version, working version, available "
                "versions, backups, and last build action."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]

_DATA_TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "query_sessions",
            "description": "Query coaching sessions from the database. CLI-Cloud ADMIN only. Returns session metadata (no transcripts/notes).",
            "parameters": {
                "type": "object",
                "properties": {
                    "client_id": {"type": "string", "description": "Filter by client username (optional)"},
                    "date_start": {"type": "string", "description": "ISO date start filter, e.g. 2026-03-01 (optional)"},
                    "date_end": {"type": "string", "description": "ISO date end filter, e.g. 2026-03-13 (optional)"},
                    "limit": {"type": "integer", "description": "Max rows to return (default 20, max 100)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_coherence_data",
            "description": "Query Nevedal coherence metrics and client biometrics. CLI-Cloud ADMIN only. Returns aggregated emotional coherence data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "client_id": {"type": "string", "description": "Filter by client username (optional)"},
                    "metric": {"type": "string", "description": "Filter by metric name, e.g. 'c_emo', 'p_ent', 'pitch_mean' (optional)"},
                    "date_start": {"type": "string", "description": "ISO date start filter (optional)"},
                    "date_end": {"type": "string", "description": "ISO date end filter (optional)"},
                    "limit": {"type": "integer", "description": "Max rows (default 50, max 200)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_user_profile",
            "description": "Query a user profile from the database. CLI-Cloud ADMIN only. Returns profile metadata (excludes password_hash and credentials).",
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {"type": "string", "description": "The username to look up"},
                },
                "required": ["username"],
            },
        },
    },
]

_SENSITIVE_PROFILE_KEYS = frozenset({
    "password", "password_hash", "credentials", "totp_secret",
    "totp_recovery_codes", "webauthn_challenge", "webauthn_challenge_issued_at",
    "webauthn_auth_challenge", "webauthn_auth_challenge_issued_at",
    "webauthn_credentials", "passphrase_answer", "security_answer",
})


async def _query_sessions_async(args: Dict[str, Any], db_pool) -> Dict[str, Any]:
    client_id = args.get("client_id")
    date_start = args.get("date_start")
    date_end = args.get("date_end")
    limit = min(args.get("limit", 20), 100)

    conditions = []
    params: list = []
    idx = 1

    if client_id:
        conditions.append(f"(cs.client_id::text = ${idx} OR cs.client_id IN (SELECT id FROM users WHERE username = ${idx}))")
        params.append(client_id)
        idx += 1
    if date_start:
        conditions.append(f"cs.created_at >= ${idx}::timestamptz")
        params.append(date_start)
        idx += 1
    if date_end:
        conditions.append(f"cs.created_at <= ${idx}::timestamptz")
        params.append(date_end)
        idx += 1

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)

    query = f"""
        SELECT cs.id, cs.session_type, cs.status, cs.payment_status,
               cs.duration_minutes, cs.created_at, cs.started_at, cs.ended_at,
               u_client.username AS client_username,
               u_coach.username AS coach_username
        FROM coaching_sessions cs
        LEFT JOIN users u_client ON cs.client_id = u_client.id
        LEFT JOIN users u_coach ON cs.coach_id = u_coach.id
        {where}
        ORDER BY cs.created_at DESC
        LIMIT ${idx}
    """

    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        results = []
        for r in rows:
            results.append({
                "id": str(r["id"]),
                "session_type": r.get("session_type"),
                "status": r.get("status"),
                "payment_status": r.get("payment_status"),
                "duration_minutes": r.get("duration_minutes"),
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                "started_at": r["started_at"].isoformat() if r.get("started_at") else None,
                "ended_at": r["ended_at"].isoformat() if r.get("ended_at") else None,
                "client": r.get("client_username"),
                "coach": r.get("coach_username"),
            })
        return {"status": "ok", "result": results, "row_count": len(results), "query_scope": {"client_id": client_id}}
    except Exception as e:
        logger.warning("query_sessions failed: %s", e)
        return {"status": "error", "error": f"Session query failed: {e}"}


async def _query_coherence_data_async(args: Dict[str, Any], db_pool) -> Dict[str, Any]:
    client_id = args.get("client_id")
    metric = args.get("metric")
    date_start = args.get("date_start")
    date_end = args.get("date_end")
    limit = min(args.get("limit", 50), 200)

    conditions = []
    params: list = []
    idx = 1

    if client_id:
        conditions.append(f"nm.user_id = ${idx}")
        params.append(client_id)
        idx += 1
    if date_start:
        conditions.append(f"nm.recorded_at >= ${idx}::timestamptz")
        params.append(date_start)
        idx += 1
    if date_end:
        conditions.append(f"nm.recorded_at <= ${idx}::timestamptz")
        params.append(date_end)
        idx += 1

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)

    query = f"""
        SELECT nm.user_id, nm.session_id, nm.recorded_at,
               nm.c_emo, nm.p_ent, nm.t_tunnel, nm.gamma_env,
               nm.pitch_mean, nm.pitch_variance, nm.energy,
               nm.speech_rate, nm.pause_ratio
        FROM nevedal_metrics nm
        {where}
        ORDER BY nm.recorded_at DESC
        LIMIT ${idx}
    """

    cm_conditions = []
    cm_params: list = []
    cm_idx = 1
    if client_id:
        cm_conditions.append(f"cm.hardware_id = ${cm_idx}")
        cm_params.append(client_id)
        cm_idx += 1
    if date_start:
        cm_conditions.append(f"cm.created_at >= ${cm_idx}::timestamptz")
        cm_params.append(date_start)
        cm_idx += 1
    if date_end:
        cm_conditions.append(f"cm.created_at <= ${cm_idx}::timestamptz")
        cm_params.append(date_end)
        cm_idx += 1
    cm_where = ("WHERE " + " AND ".join(cm_conditions)) if cm_conditions else ""
    cm_params.append(limit)

    cm_query = f"""
        SELECT cm.hardware_id AS user_id, cm.session_id, cm.created_at AS recorded_at,
               cm.coherence_score, cm.engagement_level, cm.sentiment_score,
               cm.topic_depth, cm.emotional_range
        FROM client_metrics cm
        {cm_where}
        ORDER BY cm.created_at DESC
        LIMIT ${cm_idx}
    """

    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            try:
                cm_rows = await conn.fetch(cm_query, *cm_params)
            except Exception:
                cm_rows = []

        results = []
        for r in rows:
            row_data: Dict[str, Any] = {
                "source": "nevedal_metrics",
                "user_id": r.get("user_id"),
                "session_id": str(r["session_id"]) if r.get("session_id") else None,
                "recorded_at": r["recorded_at"].isoformat() if r.get("recorded_at") else None,
            }
            metric_fields = ["c_emo", "p_ent", "t_tunnel", "gamma_env",
                             "pitch_mean", "pitch_variance", "energy",
                             "speech_rate", "pause_ratio"]
            for mf in metric_fields:
                val = r.get(mf)
                if val is not None:
                    if metric and metric != mf:
                        continue
                    row_data[mf] = float(val) if val is not None else None
            results.append(row_data)

        cm_metric_fields = ["coherence_score", "engagement_level", "sentiment_score",
                            "topic_depth", "emotional_range"]
        for r in cm_rows:
            row_data = {
                "source": "client_metrics",
                "user_id": r.get("user_id"),
                "session_id": str(r["session_id"]) if r.get("session_id") else None,
                "recorded_at": r["recorded_at"].isoformat() if r.get("recorded_at") else None,
            }
            for mf in cm_metric_fields:
                val = r.get(mf)
                if val is not None:
                    if metric and metric != mf:
                        continue
                    row_data[mf] = float(val) if val is not None else None
            results.append(row_data)

        return {"status": "ok", "result": results, "row_count": len(results), "query_scope": {"client_id": client_id, "metric": metric, "sources": ["nevedal_metrics", "client_metrics"]}}
    except Exception as e:
        logger.warning("query_coherence_data failed: %s", e)
        return {"status": "error", "error": f"Coherence query failed: {e}"}


async def _query_user_profile_async(args: Dict[str, Any], db_pool) -> Dict[str, Any]:
    username = args.get("username", "").strip()
    if not username:
        return {"status": "error", "error": "username is required"}

    query = """
        SELECT username, role, tier, subscription_status,
               profile_data, company_id, family_id, created_at
        FROM users WHERE username = $1
    """

    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(query, username)
        if not row:
            return {"status": "ok", "result": None, "row_count": 0, "query_scope": {"username": username}}

        profile = row.get("profile_data") or {}
        if isinstance(profile, str):
            try:
                profile = json.loads(profile)
            except (json.JSONDecodeError, TypeError):
                profile = {}

        safe_profile = {k: v for k, v in profile.items() if k not in _SENSITIVE_PROFILE_KEYS}

        result = {
            "username": row["username"],
            "role": row.get("role"),
            "tier": row.get("tier"),
            "subscription_status": row.get("subscription_status"),
            "name": safe_profile.get("name"),
            "email": safe_profile.get("email"),
            "phone": safe_profile.get("phone"),
            "company_id": str(row["company_id"]) if row.get("company_id") else None,
            "family_id": str(row["family_id"]) if row.get("family_id") else None,
            "token_balance": safe_profile.get("token_balance"),
            "coach_id": safe_profile.get("coach_id"),
            "assigned_coach": safe_profile.get("assigned_coach"),
            "group_id": safe_profile.get("group_id"),
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        }
        return {"status": "ok", "result": result, "row_count": 1, "query_scope": {"username": username}}
    except Exception as e:
        logger.warning("query_user_profile failed: %s", e)
        return {"status": "error", "error": f"Profile query failed: {e}"}


async def _log_data_access(
    db_pool, plan_id: Optional[str], admin_username: Optional[str],
    tool_name: str, args: Dict[str, Any], result: Dict[str, Any],
) -> None:
    """HIPAA audit: log every data-touching tool call to cli_data_access_log."""
    if db_pool is None:
        return
    try:
        redacted = {k: v for k, v in args.items() if k != "password"}
        scope = result.get("query_scope", {})
        row_count = result.get("row_count", 0)
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO cli_data_access_log
                    (plan_id, username, tool_name, data_scope, result_row_count,
                     role_tier, data_classification, redacted_args)
                VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8::jsonb)
            """,
                plan_id, admin_username or "admin", tool_name,
                json.dumps(scope), row_count, "ADMIN",
                "PHI" if tool_name in ("query_sessions", "query_coherence_data") else "internal",
                json.dumps(redacted),
            )
    except Exception as e:
        logger.warning("cli_data_access_log write failed: %s", e)


_DATA_TOOL_DISPATCH = {
    "query_sessions": _query_sessions_async,
    "query_coherence_data": _query_coherence_data_async,
    "query_user_profile": _query_user_profile_async,
}

GROK_TOOL_DEFINITIONS = list(_READ_TOOL_DEFS)

OLLAMA_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": t["function"],
    }
    for t in _READ_TOOL_DEFS
]


def _get_project_root() -> str:
    if os.path.isdir(_PROJECT_ROOT_DOCKER + "/app"):
        return _PROJECT_ROOT_DOCKER
    return _PROJECT_ROOT_LOCAL


def _is_docker() -> bool:
    return os.path.isdir(_PROJECT_ROOT_DOCKER + "/app")


def _resolve_safe_path(relative_path: str) -> Optional[str]:
    """Resolve a path for tool access.

    In Docker: strict — must stay within project root.
    Local dev: absolute paths are allowed if the file exists (user's own machine).
    """
    clean = relative_path.replace("\x00", "")

    if not _is_docker() and os.path.isabs(clean):
        real = os.path.realpath(clean)
        if os.path.exists(real):
            return real
        return None

    root = _get_project_root()
    clean = clean.lstrip("/")
    candidate = os.path.join(root, clean)
    real = os.path.realpath(candidate)
    real_root = os.path.realpath(root)
    if not real.startswith(real_root + os.sep) and real != real_root:
        return None
    return real


def _should_skip_path(path: str) -> bool:
    parts = Path(path).parts
    return any(p in _SKIP_DIRS for p in parts)


def _is_binary(path: str) -> bool:
    return Path(path).suffix.lower() in _BINARY_EXTENSIONS


def _try_r2_cache_read(path: str) -> Optional[Dict[str, Any]]:
    """Attempt to read a file from the R2 workspace cache when local file is missing.

    Uses a synchronous HTTP GET via urllib so it works without an event loop.
    Falls back to None if R2 is not configured or unreachable.
    """
    try:
        import urllib.request
        worker_url = os.environ.get("R2_WORKSPACE_WORKER_URL", "").rstrip("/")
        auth_token = os.environ.get("R2_WORKSPACE_AUTH_TOKEN", "")
        if not worker_url or not auth_token:
            return None
        safe_path = path.lstrip("/")
        url = f"{worker_url}/workspace/{safe_path}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {auth_token}"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status != 200:
                return None
            content = resp.read().decode("utf-8", errors="replace")
        lines = content.splitlines(keepends=True)
        total = len(lines)
        numbered = "".join(f"{i}|{line}" for i, line in enumerate(lines, start=1))
        return {
            "status": "ok",
            "result": numbered,
            "total_lines": total,
            "range": f"1-{total}",
            "path": path,
            "source": "r2_cache",
            "warning": "Read from R2 cache — may be stale",
        }
    except Exception:
        return None


def _read_file_sync(path: str, start_line: Optional[int], end_line: Optional[int]) -> Dict[str, Any]:
    resolved = _resolve_safe_path(path)
    if resolved is None:
        return {"status": "error", "error": f"Path traversal blocked: {path}", "error_code": _ERROR_PATH_TRAVERSAL}
    if not os.path.isfile(resolved):
        r2_result = _try_r2_cache_read(path)
        if r2_result is not None:
            return r2_result
        return {"status": "error", "error": f"File not found: {path}", "error_code": _ERROR_FILE_NOT_FOUND}
    if _is_binary(resolved):
        return {"status": "error", "error": f"Binary file, cannot read: {path}", "error_code": _ERROR_BINARY_FILE}

    try:
        file_size = os.path.getsize(resolved)
        if file_size > 5_000_000:
            return {"status": "error", "error": f"File too large ({file_size} bytes). Use start_line/end_line to read a section.", "error_code": _ERROR_TRUNCATED}

        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        total = len(lines)
        if start_line is not None and start_line < 0:
            s = max(1, total + start_line + 1)
            e = total
        else:
            s = max(1, start_line or 1)
            e = min(total, end_line or (s + 499))
        if (e - s) >= 500:
            e = s + 499

        selected = lines[s - 1 : e]
        numbered = "".join(f"{i}|{line}" for i, line in enumerate(selected, start=s))

        return {
            "status": "ok",
            "result": numbered,
            "total_lines": total,
            "range": f"{s}-{e}",
            "path": path,
        }
    except Exception as exc:
        return {"status": "error", "error": f"Read error: {exc}", "error_code": _ERROR_OTHER}


def _search_code_sync(
    pattern: str,
    search_path: Optional[str],
    glob_filter: Optional[str],
    max_results: int,
) -> Dict[str, Any]:
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        return {"status": "error", "error": f"Invalid regex: {exc}", "error_code": _ERROR_OTHER}

    root = _get_project_root()
    if search_path:
        resolved = _resolve_safe_path(search_path)
        if resolved is None:
            return {"status": "error", "error": f"Path traversal blocked: {search_path}", "error_code": _ERROR_PATH_TRAVERSAL}
        scan_root = resolved
    else:
        scan_root = root

    if not os.path.isdir(scan_root):
        return {"status": "error", "error": f"Directory not found: {search_path}", "error_code": _ERROR_FILE_NOT_FOUND}

    import fnmatch

    matches: List[Dict[str, Any]] = []
    files_scanned = 0

    for dirpath, dirnames, filenames in os.walk(scan_root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in filenames:
            if _is_binary(fname):
                continue
            if glob_filter and not fnmatch.fnmatch(fname, glob_filter):
                continue

            fpath = os.path.join(dirpath, fname)
            rel = os.path.relpath(fpath, root)
            files_scanned += 1

            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    for line_num, line in enumerate(f, 1):
                        if regex.search(line):
                            matches.append({
                                "file": rel,
                                "line_num": line_num,
                                "line_text": line.rstrip()[:300],
                            })
                            if len(matches) >= max_results:
                                return {
                                    "status": "ok",
                                    "result": matches,
                                    "total_matches": len(matches),
                                    "files_scanned": files_scanned,
                                    "truncated": True,
                                }
            except (OSError, UnicodeDecodeError):
                continue

    return {
        "status": "ok",
        "result": matches,
        "total_matches": len(matches),
        "files_scanned": files_scanned,
        "truncated": False,
    }


def _list_directory_sync(path: Optional[str], pattern: Optional[str]) -> Dict[str, Any]:
    if path:
        resolved = _resolve_safe_path(path)
        if resolved is None:
            return {"status": "error", "error": f"Path traversal blocked: {path}", "error_code": _ERROR_PATH_TRAVERSAL}
    else:
        resolved = _get_project_root()

    if not os.path.isdir(resolved):
        return {"status": "error", "error": f"Directory not found: {path or '.'}", "error_code": _ERROR_FILE_NOT_FOUND}

    import fnmatch

    entries: List[Dict[str, Any]] = []
    try:
        for name in sorted(os.listdir(resolved)):
            if name.startswith(".") and name not in (".env.template", ".cursor", ".cursorrules", ".env"):
                continue
            if name in _SKIP_DIRS:
                continue
            if pattern and not fnmatch.fnmatch(name, pattern):
                continue

            full = os.path.join(resolved, name)
            is_dir = os.path.isdir(full)
            entry: Dict[str, Any] = {"name": name, "type": "dir" if is_dir else "file"}
            if not is_dir:
                try:
                    entry["size"] = os.path.getsize(full)
                except OSError:
                    entry["size"] = 0
            entries.append(entry)
    except OSError as exc:
        return {"status": "error", "error": f"List error: {exc}", "error_code": _ERROR_OTHER}

    root = _get_project_root()
    rel = os.path.relpath(resolved, root) if resolved != root else "."
    return {"status": "ok", "result": entries, "path": rel, "count": len(entries)}


# ── Phase 2: Debug Injection Tracker (per-session state) ──

class DebugInjectionTracker:
    """Tracks files modified by inject_log so debug_cleanup can revert them."""

    def __init__(self):
        self._snapshots: Dict[str, str] = {}
        self._injection_log: List[Dict[str, Any]] = []

    @property
    def has_injections(self) -> bool:
        return len(self._snapshots) > 0

    @property
    def injected_files(self) -> List[str]:
        return list(self._snapshots.keys())

    @property
    def injection_count(self) -> int:
        return len(self._injection_log)

    def snapshot_file(self, resolved_path: str) -> bool:
        """Snapshot original content before first modification.

        Returns True if snapshot exists (already cached or newly captured).
        Returns False if the file could not be read — caller must abort the write.
        """
        if resolved_path in self._snapshots:
            return True
        try:
            with open(resolved_path, "r", encoding="utf-8", errors="replace") as f:
                self._snapshots[resolved_path] = f.read()
            return True
        except OSError as e:
            logger.warning("Failed to snapshot %s: %s — inject will be blocked", resolved_path, e)
            return False

    def record_injection(self, path: str, line: int, statement: str) -> None:
        self._injection_log.append({
            "path": path,
            "line": line,
            "statement": statement,
            "injected_at": time.time(),
        })

    def cleanup_all(self) -> Dict[str, Any]:
        """Revert all snapshotted files to their original content."""
        reverted = []
        errors = []
        for resolved_path, original in self._snapshots.items():
            try:
                with open(resolved_path, "w", encoding="utf-8") as f:
                    f.write(original)
                reverted.append(os.path.relpath(resolved_path, _get_project_root()))
            except OSError as e:
                errors.append({"path": resolved_path, "error": str(e)})
                logger.warning("Failed to revert %s: %s", resolved_path, e)

        count = len(self._snapshots)
        self._snapshots.clear()
        self._injection_log.clear()

        return {
            "status": "ok",
            "reverted_files": reverted,
            "reverted_count": len(reverted),
            "errors": errors,
            "total_injections_cleared": count,
        }

    def get_status(self) -> Dict[str, Any]:
        return {
            "files_tracked": len(self._snapshots),
            "total_injections": len(self._injection_log),
            "tracked_paths": [
                os.path.relpath(p, _get_project_root())
                for p in self._snapshots.keys()
            ],
        }


# ── Phase 2: Write tool implementations ──

def _write_file_sync(
    path: str, content: str, create_only: bool = False
) -> Dict[str, Any]:
    resolved = _resolve_safe_path(path)
    if resolved is None:
        return {"status": "error", "error": f"Path traversal blocked: {path}", "error_code": _ERROR_PATH_TRAVERSAL}
    if _is_binary(resolved):
        return {"status": "error", "error": f"Cannot write to binary file: {path}", "error_code": _ERROR_BINARY_FILE}
    if create_only and os.path.exists(resolved):
        return {"status": "error", "error": f"File already exists (create_only=true): {path}", "error_code": _ERROR_WRITE_CONFLICT}

    try:
        parent = os.path.dirname(resolved)
        if not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)

        with open(resolved, "w", encoding="utf-8") as f:
            f.write(content)

        return {
            "status": "ok",
            "result": f"Written {len(content)} chars to {path}",
            "path": path,
            "chars": len(content),
            "lines": content.count("\n") + (1 if content and not content.endswith("\n") else 0),
        }
    except Exception as exc:
        return {"status": "error", "error": f"Write error: {exc}", "error_code": _ERROR_OTHER}


def _inject_log_sync(
    path: str, line: int, statement: str,
    tracker: Optional["DebugInjectionTracker"] = None,
) -> Dict[str, Any]:
    resolved = _resolve_safe_path(path)
    if resolved is None:
        return {"status": "error", "error": f"Path traversal blocked: {path}", "error_code": _ERROR_PATH_TRAVERSAL}
    if not os.path.isfile(resolved):
        return {"status": "error", "error": f"File not found: {path}", "error_code": _ERROR_FILE_NOT_FOUND}
    if _is_binary(resolved):
        return {"status": "error", "error": f"Cannot inject into binary file: {path}", "error_code": _ERROR_BINARY_FILE}

    try:
        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        if line < 1 or line > len(lines) + 1:
            return {"status": "error", "error": f"Line {line} out of range (file has {len(lines)} lines)", "error_code": _ERROR_OTHER}

        if tracker:
            if not tracker.snapshot_file(resolved):
                return {"status": "error", "error": f"Cannot snapshot {path} — inject blocked to preserve revert ability", "error_code": _ERROR_PERMISSION_DENIED}

        inject_line = statement if statement.endswith("\n") else statement + "\n"
        lines.insert(line - 1, inject_line)

        with open(resolved, "w", encoding="utf-8") as f:
            f.writelines(lines)

        if tracker:
            tracker.record_injection(path, line, statement)

        return {
            "status": "ok",
            "result": f"Injected at {path}:{line}",
            "path": path,
            "line": line,
            "statement": statement.strip(),
            "total_lines_after": len(lines),
        }
    except Exception as exc:
        return {"status": "error", "error": f"Inject error: {exc}", "error_code": _ERROR_OTHER}


def _debug_cleanup_sync(
    tracker: Optional["DebugInjectionTracker"] = None,
) -> Dict[str, Any]:
    if tracker is None or not tracker.has_injections:
        return {"status": "ok", "result": "No debug injections to clean up", "reverted_count": 0}
    return tracker.cleanup_all()


# ── Phase 5: Cursor-parity tool implementations ──

def _str_replace_sync(
    path: str, old_string: str, new_string: str, replace_all: bool = False
) -> Dict[str, Any]:
    resolved = _resolve_safe_path(path)
    if resolved is None:
        return {"status": "error", "error": f"Path traversal blocked: {path}", "error_code": _ERROR_PATH_TRAVERSAL}
    if not os.path.isfile(resolved):
        return {"status": "error", "error": f"File not found: {path}", "error_code": _ERROR_FILE_NOT_FOUND}
    if _is_binary(resolved):
        return {"status": "error", "error": f"Cannot edit binary file: {path}", "error_code": _ERROR_BINARY_FILE}

    try:
        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        if old_string == new_string:
            return {"status": "error", "error": "old_string and new_string are identical", "error_code": _ERROR_OTHER}

        count = content.count(old_string)
        if count == 0:
            preview = old_string[:100]
            return {"status": "error", "error": f"old_string not found in {path}. First 100 chars: {preview!r}", "error_code": _ERROR_WRITE_CONFLICT}

        if count > 1 and not replace_all:
            return {
                "status": "error",
                "error": f"old_string found {count} times in {path}. Include more context to make it unique, or set replace_all=true.",
            }

        if replace_all:
            new_content = content.replace(old_string, new_string)
            replacements = count
        else:
            new_content = content.replace(old_string, new_string, 1)
            replacements = 1

        with open(resolved, "w", encoding="utf-8") as f:
            f.write(new_content)

        return {
            "status": "ok",
            "result": f"Replaced {replacements} occurrence{'s' if replacements != 1 else ''} in {path}",
            "path": path,
            "replacements": replacements,
        }
    except Exception as exc:
        return {"status": "error", "error": f"str_replace error: {exc}", "error_code": _ERROR_OTHER}


def _delete_file_sync(path: str) -> Dict[str, Any]:
    resolved = _resolve_safe_path(path)
    if resolved is None:
        return {"status": "error", "error": f"Path traversal blocked: {path}", "error_code": _ERROR_PATH_TRAVERSAL}
    if not os.path.isfile(resolved):
        return {"status": "error", "error": f"File not found: {path}", "error_code": _ERROR_FILE_NOT_FOUND}

    try:
        os.remove(resolved)
        return {"status": "ok", "result": f"Deleted {path}"}
    except Exception as exc:
        return {"status": "error", "error": f"Delete error: {exc}", "error_code": _ERROR_OTHER}


def _grep_sync(
    pattern: str,
    search_path: Optional[str] = None,
    glob_filter: Optional[str] = None,
    context_lines: int = 2,
    max_results: int = 30,
    case_insensitive: bool = False,
    output_mode: str = "content",
    multiline: bool = False,
    before_context: Optional[int] = None,
    after_context: Optional[int] = None,
    head_limit: Optional[int] = None,
    result_offset: int = 0,
    file_type: Optional[str] = None,
) -> Dict[str, Any]:
    flags = re.IGNORECASE if case_insensitive else 0
    if multiline:
        flags |= re.DOTALL | re.MULTILINE
    try:
        regex = re.compile(pattern, flags)
    except re.error as exc:
        return {"status": "error", "error": f"Invalid regex: {exc}", "error_code": _ERROR_OTHER}

    ctx_before = max(0, min(before_context if before_context is not None else context_lines, 10))
    ctx_after = max(0, min(after_context if after_context is not None else context_lines, 10))
    effective_limit = head_limit if head_limit is not None else max_results

    type_globs = None
    if file_type and file_type in _FILE_TYPE_EXTENSIONS:
        type_globs = _FILE_TYPE_EXTENSIONS[file_type]

    root = _get_project_root()
    if search_path:
        resolved = _resolve_safe_path(search_path)
        if resolved is None:
            return {"status": "error", "error": f"Path traversal blocked: {search_path}", "error_code": _ERROR_PATH_TRAVERSAL}
        if os.path.isfile(resolved):
            scan_targets = [(resolved, os.path.relpath(resolved, root))]
        elif os.path.isdir(resolved):
            scan_targets = None
            scan_root = resolved
        else:
            return {"status": "error", "error": f"Path not found: {search_path}", "error_code": _ERROR_FILE_NOT_FOUND}
    else:
        scan_targets = None
        scan_root = root

    if output_mode == "files_with_matches":
        return _grep_files_mode(regex, root, scan_targets, scan_root if not scan_targets else root,
                                glob_filter, type_globs, multiline, effective_limit, result_offset)
    if output_mode == "count":
        return _grep_count_mode(regex, root, scan_targets, scan_root if not scan_targets else root,
                                glob_filter, type_globs, multiline, effective_limit, result_offset)

    results: List[Dict[str, Any]] = []
    files_scanned = 0
    skipped = 0

    def _scan_file(fpath: str, rel: str):
        nonlocal files_scanned, skipped
        files_scanned += 1
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                file_text = f.read()
        except (OSError, UnicodeDecodeError):
            return

        if multiline:
            for m in regex.finditer(file_text):
                line_num = file_text[:m.start()].count("\n") + 1
                match_text = m.group()[:300]
                if skipped < result_offset:
                    skipped += 1
                    continue
                results.append({"file": rel, "line_num": line_num, "match": match_text, "context": ""})
                if len(results) >= effective_limit:
                    return
        else:
            lines = file_text.splitlines(True)
            for i, line in enumerate(lines):
                if regex.search(line):
                    if skipped < result_offset:
                        skipped += 1
                        continue
                    start = max(0, i - ctx_before)
                    end = min(len(lines), i + ctx_after + 1)
                    context_block = []
                    for j in range(start, end):
                        prefix = ":" if j == i else "-"
                        context_block.append(f"{j+1}{prefix}{lines[j].rstrip()}")
                    results.append({
                        "file": rel,
                        "line_num": i + 1,
                        "match": line.rstrip()[:300],
                        "context": "\n".join(context_block),
                    })
                    if len(results) >= effective_limit:
                        return

    def _matches_filters(fname: str) -> bool:
        if _is_binary(fname):
            return False
        if type_globs:
            return any(fnmatch.fnmatch(fname, g) for g in type_globs)
        if glob_filter:
            for g in glob_filter.split(","):
                g = g.strip()
                if g.startswith("{") and g.endswith("}"):
                    for ext in g[1:-1].split(","):
                        if fnmatch.fnmatch(fname, f"*.{ext.strip()}"):
                            return True
                elif fnmatch.fnmatch(fname, g):
                    return True
            return False
        return True

    if scan_targets:
        for fpath, rel in scan_targets:
            _scan_file(fpath, rel)
    else:
        for dirpath, dirnames, filenames in os.walk(scan_root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fname in filenames:
                if not _matches_filters(fname):
                    continue
                fpath = os.path.join(dirpath, fname)
                rel = os.path.relpath(fpath, root)
                _scan_file(fpath, rel)
                if len(results) >= effective_limit:
                    break
            if len(results) >= effective_limit:
                break

    return {
        "status": "ok",
        "result": results,
        "total_matches": len(results),
        "files_scanned": files_scanned,
        "truncated": len(results) >= effective_limit,
    }


def _grep_files_mode(regex, root, scan_targets, scan_root, glob_filter, type_globs, multiline, limit, offset):
    matching_files = []
    files_scanned = 0

    def _check_file(fpath, rel):
        nonlocal files_scanned
        files_scanned += 1
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            if regex.search(content):
                matching_files.append(rel)
        except (OSError, UnicodeDecodeError):
            pass

    def _matches(fname):
        if _is_binary(fname):
            return False
        if type_globs:
            return any(fnmatch.fnmatch(fname, g) for g in type_globs)
        if glob_filter:
            return any(fnmatch.fnmatch(fname, g.strip()) for g in glob_filter.split(","))
        return True

    if scan_targets:
        for fpath, rel in scan_targets:
            _check_file(fpath, rel)
    else:
        for dirpath, dirnames, filenames in os.walk(scan_root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fname in filenames:
                if not _matches(fname):
                    continue
                _check_file(os.path.join(dirpath, fname), os.path.relpath(os.path.join(dirpath, fname), root))
                if len(matching_files) >= offset + limit + 50:
                    break
            if len(matching_files) >= offset + limit + 50:
                break

    sliced = matching_files[offset:offset + limit]
    return {"status": "ok", "result": sliced, "total_matches": len(matching_files), "files_scanned": files_scanned}


def _grep_count_mode(regex, root, scan_targets, scan_root, glob_filter, type_globs, multiline, limit, offset):
    counts = []
    files_scanned = 0

    def _count_file(fpath, rel):
        nonlocal files_scanned
        files_scanned += 1
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            n = len(regex.findall(content))
            if n > 0:
                counts.append({"file": rel, "count": n})
        except (OSError, UnicodeDecodeError):
            pass

    def _matches(fname):
        if _is_binary(fname):
            return False
        if type_globs:
            return any(fnmatch.fnmatch(fname, g) for g in type_globs)
        if glob_filter:
            return any(fnmatch.fnmatch(fname, g.strip()) for g in glob_filter.split(","))
        return True

    if scan_targets:
        for fpath, rel in scan_targets:
            _count_file(fpath, rel)
    else:
        for dirpath, dirnames, filenames in os.walk(scan_root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fname in filenames:
                if not _matches(fname):
                    continue
                _count_file(os.path.join(dirpath, fname), os.path.relpath(os.path.join(dirpath, fname), root))

    sliced = counts[offset:offset + limit]
    return {"status": "ok", "result": sliced, "total_files_with_matches": len(counts), "files_scanned": files_scanned}


def _glob_sync(pattern: str, target_directory: Optional[str] = None) -> Dict[str, Any]:
    root = _get_project_root()
    if target_directory:
        resolved = _resolve_safe_path(target_directory)
        if resolved is None:
            return {"status": "error", "error": f"Path traversal blocked: {target_directory}", "error_code": _ERROR_PATH_TRAVERSAL}
        if not os.path.isdir(resolved):
            return {"status": "error", "error": f"Directory not found: {target_directory}", "error_code": _ERROR_FILE_NOT_FOUND}
        scan_root = resolved
    else:
        scan_root = root

    if not pattern.startswith("**/") and "/" not in pattern:
        pattern = "**/" + pattern

    matches = []
    try:
        for match in Path(scan_root).glob(pattern):
            if any(p in _SKIP_DIRS for p in match.parts):
                continue
            if match.is_file():
                rel = str(match.relative_to(root)) if str(match).startswith(root) else str(match.relative_to(scan_root))
                try:
                    mtime = match.stat().st_mtime
                except OSError:
                    mtime = 0
                matches.append({"path": rel, "mtime": mtime})
                if len(matches) >= 200:
                    break
    except Exception as exc:
        return {"status": "error", "error": f"Glob error: {exc}", "error_code": _ERROR_OTHER}

    matches.sort(key=lambda x: x["mtime"], reverse=True)
    paths = [m["path"] for m in matches]

    return {
        "status": "ok",
        "result": paths,
        "total_matches": len(paths),
    }


def _shell_sync(
    command: str,
    working_directory: Optional[str] = None,
    block_until_ms: int = 30000,
    description: str = "",
) -> Dict[str, Any]:
    root = _get_project_root()
    if working_directory:
        resolved = _resolve_safe_path(working_directory)
        if resolved is None:
            return {"status": "error", "error": f"Path traversal blocked: {working_directory}", "error_code": _ERROR_PATH_TRAVERSAL}
        cwd = resolved
    else:
        cwd = root

    _BLOCKED_PATTERNS = [
        r"\brm\s+-rf\s+/",
        r"\bmkfs\b",
        r"\bdd\s+if=",
        r">\s*/dev/sd",
        r"\bshutdown\b",
        r"\breboot\b",
        r"\bsudo\s+rm\s+-rf\b",
    ]
    for bp in _BLOCKED_PATTERNS:
        if re.search(bp, command):
            return {"status": "error", "error": f"Blocked dangerous command pattern: {bp}", "error_code": _ERROR_PERMISSION_DENIED}

    timeout_s = max(1, min(block_until_ms / 1000, 300))

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )

        stdout = result.stdout[:12000] if result.stdout else ""
        stderr = result.stderr[:6000] if result.stderr else ""

        out = {
            "status": "ok" if result.returncode == 0 else "error",
            "result": stdout,
            "stderr": stderr,
            "exit_code": result.returncode,
            "command": command[:200],
            "elapsed_ms": int(timeout_s * 1000),
        }
        if result.returncode != 0:
            out["error_code"] = _ERROR_SHELL_NONZERO
        return out
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": f"Command timed out after {timeout_s:.0f}s: {command[:100]}. Increase block_until_ms for long-running commands.", "error_code": _ERROR_TIMEOUT}
    except Exception as exc:
        return {"status": "error", "error": f"Shell error: {exc}", "error_code": _ERROR_OTHER}


_LINT_EXTENSIONS = {".py", ".dart", ".js", ".ts", ".tsx", ".jsx", ".mjs"}


def _read_lints_sync(paths: List[str]) -> Dict[str, Any]:
    root = _get_project_root()
    file_paths: List[str] = []

    for p in paths[:20]:
        resolved = _resolve_safe_path(p)
        if resolved is None:
            continue
        if os.path.isdir(resolved):
            for dp, _, fnames in os.walk(resolved):
                dp_parts = Path(dp).parts
                if any(skip in dp_parts for skip in _SKIP_DIRS):
                    continue
                for fn in fnames:
                    if Path(fn).suffix.lower() in _LINT_EXTENSIONS:
                        file_paths.append(os.path.join(dp, fn))
                        if len(file_paths) >= 50:
                            break
                if len(file_paths) >= 50:
                    break
        elif os.path.isfile(resolved):
            file_paths.append(resolved)

    diagnostics = []
    for resolved in file_paths[:50]:
        rel = os.path.relpath(resolved, root) if resolved.startswith(root) else resolved
        errors = []
        ext = Path(resolved).suffix.lower()

        if ext == ".py":
            try:
                result = subprocess.run(
                    ["python3", "-m", "py_compile", resolved],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode != 0:
                    for line in (result.stderr or "").strip().splitlines():
                        errors.append({"message": line.strip(), "severity": "error"})
            except Exception as exc:
                errors.append({"message": f"Lint check failed: {exc}", "severity": "warning"})

            try:
                with open(resolved, "r", encoding="utf-8") as f:
                    source = f.read()
                compile(source, resolved, "exec")
            except SyntaxError as se:
                errors.append({
                    "message": f"SyntaxError: {se.msg}",
                    "line": se.lineno,
                    "col": se.offset,
                    "severity": "error",
                })

        elif ext == ".dart":
            try:
                result = subprocess.run(
                    ["dart", "analyze", "--fatal-infos", resolved],
                    capture_output=True, text=True, timeout=15, cwd=root,
                )
                if result.returncode != 0:
                    for line in (result.stdout or "").strip().splitlines()[:20]:
                        if "error" in line.lower() or "warning" in line.lower() or "info" in line.lower():
                            errors.append({"message": line.strip(), "severity": "error"})
            except FileNotFoundError:
                pass
            except Exception:
                pass

        elif ext in (".js", ".ts", ".tsx", ".jsx", ".mjs"):
            try:
                with open(resolved, "r", encoding="utf-8") as f:
                    source = f.read()
                _js_checks = [
                    (r"(?<!\w)function\s+\(", "Possible missing function name"),
                    (r"\bconsole\.log\b", "console.log found (debug artifact?)"),
                ]
                for pat, msg in _js_checks:
                    for m in re.finditer(pat, source):
                        ln = source[:m.start()].count("\n") + 1
                        errors.append({"message": msg, "line": ln, "severity": "warning"})
            except Exception:
                pass

            for node_cmd in ["npx", "node"]:
                try:
                    result = subprocess.run(
                        [node_cmd, "--check", resolved] if node_cmd == "node" and ext in (".js", ".mjs") else
                        ["npx", "tsc", "--noEmit", "--allowJs", resolved] if ext in (".ts", ".tsx") else
                        [node_cmd, "--check", resolved],
                        capture_output=True, text=True, timeout=10,
                    )
                    if result.returncode != 0 and result.stderr:
                        for line in result.stderr.strip().splitlines()[:10]:
                            errors.append({"message": line.strip(), "severity": "error"})
                    break
                except FileNotFoundError:
                    continue
                except Exception:
                    break

        diagnostics.append({
            "path": rel,
            "errors": errors,
            "clean": len(errors) == 0,
        })

    return {
        "status": "ok",
        "result": diagnostics,
        "total_files": len(diagnostics),
        "files_with_errors": sum(1 for d in diagnostics if d.get("errors")),
    }


_SESSION_TODO_STORE: Dict[str, List[Dict[str, str]]] = {}


def _web_fetch_sync(url: str) -> Dict[str, Any]:
    import urllib.request
    import urllib.error
    import html.parser

    if not url.startswith(("http://", "https://")):
        return {"status": "error", "error": "URL must start with http:// or https://", "error_code": _ERROR_OTHER}

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "LittleNate-CLI/1.0 (WebFetch tool)",
            "Accept": "text/html,application/xhtml+xml,text/plain,application/json",
        })
        with urllib.request.urlopen(req, timeout=12) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if any(b in content_type for b in ("image/", "audio/", "video/", "application/pdf", "application/octet")):
                return {"status": "error", "error": f"Binary content type not supported: {content_type}", "error_code": _ERROR_BINARY_FILE}
            raw = resp.read(500_000).decode("utf-8", errors="replace")

        if "text/html" in content_type:
            class _TextExtractor(html.parser.HTMLParser):
                def __init__(self):
                    super().__init__()
                    self._texts: list = []
                    self._skip = False
                    self._skip_tags = {"script", "style", "noscript", "svg"}
                def handle_starttag(self, tag, _):
                    if tag in self._skip_tags:
                        self._skip = True
                def handle_endtag(self, tag):
                    if tag in self._skip_tags:
                        self._skip = False
                def handle_data(self, data):
                    if not self._skip:
                        stripped = data.strip()
                        if stripped:
                            self._texts.append(stripped)
                def get_text(self):
                    return "\n".join(self._texts)

            parser = _TextExtractor()
            parser.feed(raw)
            text = parser.get_text()[:20000]
        else:
            text = raw[:20000]

        return {
            "status": "ok",
            "result": text,
            "url": url,
            "content_type": content_type,
            "length": len(text),
        }
    except urllib.error.HTTPError as e:
        return {"status": "error", "error": f"HTTP {e.code}: {e.reason}", "error_code": _ERROR_OTHER}
    except urllib.error.URLError as e:
        return {"status": "error", "error": f"URL error: {e.reason}", "error_code": _ERROR_TIMEOUT if "timed out" in str(e.reason).lower() else _ERROR_OTHER}
    except Exception as exc:
        return {"status": "error", "error": f"Fetch error: {exc}", "error_code": _ERROR_OTHER}


def _web_search_local_sync(query: str) -> Dict[str, Any]:
    """Search the web via DuckDuckGo Lite (Gap Audit 1B). No API key, no Grok."""
    import urllib.request
    import urllib.error
    import urllib.parse

    query = (query or "").strip()
    if not query:
        return {"status": "error", "error": "query is required", "error_code": _ERROR_OTHER}

    url = f"https://lite.duckduckgo.com/lite/?q={urllib.parse.quote(query)}"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "LittleNate-CLI/1.0 (WebSearchLocal)",
            "Accept": "text/html",
        })
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read(500_000).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return {"status": "error", "error": f"HTTP {e.code}: {e.reason}", "error_code": _ERROR_OTHER}
    except urllib.error.URLError as e:
        return {"status": "error", "error": f"URL error: {e.reason}", "error_code": _ERROR_TIMEOUT if "timed out" in str(e.reason).lower() else _ERROR_OTHER}
    except Exception as exc:
        return {"status": "error", "error": f"Search error: {exc}", "error_code": _ERROR_OTHER}

    # DDG Lite: extract links with uddg= (real URL) and title from link text
    results: List[Dict[str, str]] = []
    for m in re.finditer(r'<a[^>]+href="[^"]*uddg=([^&"\'<>]+)[^"]*"[^>]*>([^<]+)</a>', raw, re.IGNORECASE | re.DOTALL):
        if len(results) >= 10:
            break
        try:
            dec_url = urllib.parse.unquote(m.group(1))
            title = m.group(2).strip()
            if dec_url.startswith("http") and title and len(title) > 3:
                # Look for snippet (next block of text after the link, before next link)
                snippet = ""
                after = raw[m.end():m.end() + 600]
                snip_m = re.search(r'</a>\s*[|<][^>]*>\s*([^<|]{30,400})', after, re.DOTALL)
                if snip_m:
                    snippet = re.sub(r'\s+', ' ', snip_m.group(1)).strip()[:300]
                results.append({"title": title[:150], "url": dec_url[:500], "snippet": snippet})
        except Exception:
            continue

    out_lines = []
    for i, r in enumerate(results[:10], 1):
        out_lines.append(f"{i}. {r.get('title', '')}")
        out_lines.append(f"   URL: {r.get('url', '')}")
        if r.get("snippet"):
            out_lines.append(f"   {r['snippet']}")
        out_lines.append("")

    return {
        "status": "ok",
        "result": "\n".join(out_lines) if out_lines else "No results found.",
        "query": query,
        "count": len(results),
    }


def _todo_write_sync(
    todos: List[Dict[str, str]],
    merge: bool = False,
    session_key: str = "_default",
) -> Dict[str, Any]:
    existing = _SESSION_TODO_STORE.get(session_key, [])

    if merge and existing:
        by_id = {t["id"]: t for t in existing}
        for t in todos:
            tid = t.get("id", "")
            if tid in by_id:
                if t.get("content"):
                    by_id[tid]["content"] = t["content"]
                if t.get("status"):
                    by_id[tid]["status"] = t["status"]
            else:
                by_id[tid] = {"id": tid, "content": t.get("content", ""), "status": t.get("status", "pending")}
        updated = list(by_id.values())
    else:
        updated = [{"id": t.get("id", f"t{i}"), "content": t.get("content", ""), "status": t.get("status", "pending")}
                    for i, t in enumerate(todos)]

    _SESSION_TODO_STORE[session_key] = updated

    summary_lines = []
    for t in updated:
        icon = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]", "cancelled": "[-]"}.get(t["status"], "[ ]")
        summary_lines.append(f"{icon} {t['content']} ({t['id']})")

    return {
        "status": "ok",
        "result": "\n".join(summary_lines),
        "total": len(updated),
        "completed": sum(1 for t in updated if t["status"] == "completed"),
        "in_progress": sum(1 for t in updated if t["status"] == "in_progress"),
    }


def _switch_mode_sync(target_mode: str, explanation: str = "") -> Dict[str, Any]:
    valid = {"ask", "plan", "ln_fab", "debug"}
    if target_mode not in valid:
        return {"status": "error", "error": f"Invalid mode '{target_mode}'. Must be one of: {', '.join(sorted(valid))}", "error_code": _ERROR_OTHER}

    mode_labels = {"ask": "ASK", "plan": "PLAN", "ln_fab": "LN-FAB (Build)", "debug": "DEBUG"}
    label = mode_labels.get(target_mode, target_mode.upper())

    return {
        "status": "ok",
        "result": f"MODE SWITCH RECOMMENDED → {label}\n{explanation}\n\nTo switch: start a new CLI session with mode={target_mode}",
        "target_mode": target_mode,
        "explanation": explanation,
        "action": "mode_switch_suggested",
    }


def _provider_stats_sync() -> Dict[str, Any]:
    try:
        from app.services.provider_tracker import get_session_stats, _parse_jsonl_logs
        session = get_session_stats()
        alltime = _parse_jsonl_logs()
    except Exception as e:
        return {"status": "error", "error": f"Provider tracker unavailable: {e}", "error_code": _ERROR_OTHER}

    lines = ["═══ PROVIDER UTILIZATION ═══", ""]

    lines.append("── Session ──")
    lines.append(f"  Uptime: {session.get('session_uptime_s', 0)}s | Calls: {session.get('total_calls', 0)} | Cost: ${session.get('total_cost_usd', 0):.6f}")
    lines.append(f"  Savings vs Grok: ${session.get('savings_vs_grok', 0):.6f} | vs Azure: ${session.get('savings_vs_azure', 0):.6f}")
    for prov, s in sorted(session.get("by_provider", {}).items()):
        lines.append(f"    {prov:15s}  {s['calls']:4d} calls ({s['pct']:5.1f}%)  avg {s.get('avg_ms', 0):5d}ms  ${s.get('cost_usd', 0):.6f}")

    lines.append("")
    lines.append("── All-Time (JSONL log) ──")
    lines.append(f"  Calls: {alltime.get('total_calls', 0)} | Cost: ${alltime.get('total_cost_usd', 0):.6f} | Savings vs Grok: ${alltime.get('savings_vs_grok', 0):.6f}")
    for prov, s in sorted(alltime.get("by_provider", {}).items()):
        lines.append(f"    {prov:15s}  {s['calls']:4d} calls ({s.get('pct', 0):5.1f}%)  ${s.get('cost_usd', 0):.6f}")

    return {"status": "ok", "result": "\n".join(lines)}


# --- Build System Tool Implementations ---

def _get_build_manager():
    """Lazy-load the VersionedBuildManager singleton."""
    from app.websocket.versioned_build_manager import VersionedBuildManager
    return VersionedBuildManager()


def _build_start_sync(bump_level: str = "patch") -> Dict[str, Any]:
    try:
        mgr = _get_build_manager()
        result = mgr.build_start(bump_level=bump_level)
        if not result.get("ok"):
            return {"status": "error", "error": result.get("error", "Unknown error"), "error_code": _ERROR_OTHER}

        lines = [
            "═══ BUILD STARTED ═══",
            f"  Stable version: {result['stable_version']}",
            f"  New version:    {result['new_version']}",
            f"  Working dir:    {result['working_dir']}",
            f"  Backup dir:     {result['backup_dir']}",
            "",
            "All file edits should now target the working version.",
            "Run build_test when ready to verify.",
        ]
        return {"status": "ok", "result": "\n".join(lines)}
    except Exception as e:
        return {"status": "error", "error": f"build_start failed: {e}", "error_code": _ERROR_OTHER}


def _build_test_sync() -> Dict[str, Any]:
    try:
        mgr = _get_build_manager()
        working = mgr.get_working_dir()
        if not working:
            stable = mgr.get_stable_version()
            if stable:
                working = mgr._versions_dir / stable
            else:
                working = mgr.project_root

        from app.websocket.build_test_suite import BuildTestSuite
        suite = BuildTestSuite(str(working), str(mgr.project_root))

        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = pool.submit(lambda: asyncio.run(suite.run_all())).result(timeout=60)
        else:
            result = asyncio.run(suite.run_all())

        lines = ["═══ BUILD TEST RESULTS ═══", ""]
        for c in result.checks:
            mark = "✓" if c.passed else "✗"
            lines.append(f"  {mark} {c.name}: {c.detail} ({c.duration_ms:.0f}ms)")
        lines.append("")
        if result.all_passed:
            lines.append("ALL 6 CHECKS PASSED — ready for Orange verification or promotion.")
        else:
            failed = [c.name for c in result.checks if not c.passed]
            lines.append(f"FAILED: {', '.join(failed)} — fix before promotion.")

        return {"status": "ok", "result": "\n".join(lines), "test_results": result.to_dict()}
    except Exception as e:
        return {"status": "error", "error": f"build_test failed: {e}", "error_code": _ERROR_OTHER}


def _build_promote_sync(cli: str = "blue") -> Dict[str, Any]:
    try:
        mgr = _get_build_manager()
        result = mgr.build_promote(cli=cli)
        if not result.get("ok"):
            return {"status": "error", "error": result.get("error", "Unknown error"), "error_code": _ERROR_OTHER}

        lines = [
            "═══ BUILD PROMOTED ═══",
            f"  Promoted: {result['promoted']}",
            f"  Previous: {result['previous']}",
            f"  Live path: {result['live_path']}",
            "",
            f"  {cli.upper()} is now LIVE on {result['promoted']}.",
        ]
        if cli == "blue":
            lines.append("  Green still on previous version (safety net).")
            lines.append("  Monitor for errors before promoting Green.")
        return {"status": "ok", "result": "\n".join(lines)}
    except Exception as e:
        return {"status": "error", "error": f"build_promote failed: {e}", "error_code": _ERROR_OTHER}


def _build_rollback_sync(target_version: Optional[str] = None) -> Dict[str, Any]:
    try:
        mgr = _get_build_manager()
        result = mgr.build_rollback(target_version=target_version)
        if not result.get("ok"):
            return {"status": "error", "error": result.get("error", "Unknown error"), "error_code": _ERROR_OTHER}

        lines = [
            "═══ ROLLBACK COMPLETE ═══",
            f"  Rolled back from: {result['rolled_back_from']}",
            f"  Rolled back to:   {result['rolled_back_to']}",
            f"  Live path:        {result['live_path']}",
            "",
            "Bridge restart required to run the rolled-back version.",
        ]
        return {"status": "ok", "result": "\n".join(lines)}
    except Exception as e:
        return {"status": "error", "error": f"build_rollback failed: {e}", "error_code": _ERROR_OTHER}


def _build_status_sync() -> Dict[str, Any]:
    try:
        mgr = _get_build_manager()
        status = mgr.get_status()

        lines = [
            "═══ BUILD STATUS ═══",
            f"  Stable version: {status['stable_version'] or '(none)'}",
            f"  Current build:  {status['current_build'] or '(none)'}",
            f"  Live target:    {status['live_target'] or '(not set)'}",
            f"  Versions:       {', '.join(status['available_versions']) or '(none)'}",
            f"  Backups:        {', '.join(status['backups']) or '(none)'}",
            f"  History:        {status['history_count']} records",
        ]
        if status.get("last_action"):
            la = status["last_action"]
            lines.append(f"  Last action:    {la.get('action')} {la.get('version')} at {la.get('timestamp', '')[:19]}")
        return {"status": "ok", "result": "\n".join(lines)}
    except Exception as e:
        return {"status": "error", "error": f"build_status failed: {e}", "error_code": _ERROR_OTHER}


_DATA_TOOLS = {"query_sessions", "query_coherence_data", "query_user_profile"}

_READ_TOOL_DISPATCH = {
    "read_file": lambda args, **_: _read_file_sync(
        args.get("path", ""),
        args.get("start_line"),
        args.get("end_line"),
    ),
    "search_code": lambda args, **_: _search_code_sync(
        args.get("pattern", ""),
        args.get("path"),
        args.get("glob"),
        args.get("max_results", 20),
    ),
    "list_directory": lambda args, **_: _list_directory_sync(
        args.get("path"),
        args.get("pattern"),
    ),
}

_WRITE_TOOL_DISPATCH = {
    "write_file": lambda args, **kw: _write_file_sync(
        args.get("path", ""),
        args.get("content", ""),
        args.get("create_only", False),
    ),
    "str_replace": lambda args, **kw: _str_replace_sync(
        args.get("path", ""),
        args.get("old_string", ""),
        args.get("new_string", ""),
        args.get("replace_all", False),
    ),
    "delete_file": lambda args, **kw: _delete_file_sync(
        args.get("path", ""),
    ),
    "inject_log": lambda args, **kw: _inject_log_sync(
        args.get("path", ""),
        args.get("line", 0),
        args.get("statement", ""),
        tracker=kw.get("tracker"),
    ),
    "debug_cleanup": lambda args, **kw: _debug_cleanup_sync(
        tracker=kw.get("tracker"),
    ),
}

_PHASE5_TOOL_DISPATCH = {
    "grep": lambda args, **kw: _grep_sync(
        args.get("pattern", ""),
        args.get("path"),
        args.get("glob"),
        args.get("context_lines", 2),
        args.get("max_results", 30),
        args.get("case_insensitive", False),
        output_mode=args.get("output_mode", "content"),
        multiline=args.get("multiline", False),
        before_context=args.get("B"),
        after_context=args.get("A"),
        head_limit=args.get("head_limit"),
        result_offset=args.get("offset", 0),
        file_type=args.get("type"),
    ),
    "glob": lambda args, **kw: _glob_sync(
        args.get("pattern", ""),
        args.get("target_directory"),
    ),
    "shell": lambda args, **kw: _shell_sync(
        args.get("command", ""),
        args.get("working_directory"),
        block_until_ms=args.get("block_until_ms", 30000),
        description=args.get("description", ""),
    ),
    "read_lints": lambda args, **kw: _read_lints_sync(
        args.get("paths", []),
    ),
}

_PHASE6_TOOL_DISPATCH = {
    "web_fetch": lambda args, **kw: _web_fetch_sync(args.get("url", "")),
    "web_search_local": lambda args, **kw: _web_search_local_sync(args.get("query", "")),
    "todo_write": lambda args, **kw: _todo_write_sync(
        args.get("todos", []),
        args.get("merge", False),
    ),
    "switch_mode": lambda args, **kw: _switch_mode_sync(
        args.get("target_mode", "ask"),
        args.get("explanation", ""),
    ),
    "provider_stats": lambda args, **kw: _provider_stats_sync(),
}

_BUILD_TOOL_DISPATCH = {
    "build_start": lambda args, **kw: _build_start_sync(args.get("bump_level", "patch")),
    "build_test": lambda args, **kw: _build_test_sync(),
    "build_promote": lambda args, **kw: _build_promote_sync(args.get("cli", "blue")),
    "build_rollback": lambda args, **kw: _build_rollback_sync(args.get("target_version")),
    "build_status": lambda args, **kw: _build_status_sync(),
}

_TOOL_DISPATCH = {**_READ_TOOL_DISPATCH, **_WRITE_TOOL_DISPATCH, **_PHASE5_TOOL_DISPATCH, **_PHASE6_TOOL_DISPATCH, **_BUILD_TOOL_DISPATCH}


def _normalize_ln_tool_result(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Map LN tool dicts (success/result) to CLI tool shape (status/content)."""
    if raw.get("status") in ("ok", "error"):
        return raw
    ok = bool(raw.get("success", False))
    if not ok:
        return {
            "status": "error",
            "error": str(raw.get("error", "tool failed")),
            "error_code": raw.get("error_code", _ERROR_OTHER),
            "provider": "ln_tools",
        }
    res = raw.get("result", "")
    if not isinstance(res, str):
        try:
            res = json.dumps(res, default=str)
        except TypeError:
            res = str(res)
    meta = {k: v for k, v in raw.items() if k not in ("success", "result", "error")}
    return {
        "status": "ok",
        "content": res,
        "provider": "ln_tools",
        "metadata": meta,
    }


async def _execute_ln_tool(
    name: str,
    args: Dict[str, Any],
    *,
    cli_type: str,
    mode: str,
    send_to_extension: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
) -> Dict[str, Any]:
    """Dispatch async LN infrastructure tools (app.websocket.tools)."""
    if not _LN_TOOLS_AVAILABLE:
        return {"status": "error", "error": "LN tools package unavailable", "error_code": _ERROR_OTHER}

    from app.websocket.tools import (
        handle_ask_user,
        handle_batch_grep,
        handle_batch_read,
        handle_git_write,
        handle_ssh_deploy,
        handle_ssh_exec,
    )

    if name == "ask_user":
        if send_to_extension is None:
            return {
                "status": "error",
                "error": "ask_user requires an active Sovereign IDE WebSocket (no UI channel).",
                "error_code": _ERROR_PERMISSION_DENIED,
            }
        raw = await handle_ask_user(
            args,
            send_to_extension,
            timeout=TOOL_TIMEOUTS.get("ask_user", 300),
        )
        return _normalize_ln_tool_result(raw)

    if name == "batch_read":

        def _read_adapter(params: Dict[str, Any]) -> Dict[str, Any]:
            r = _read_file_sync(
                params.get("path", ""),
                params.get("start_line"),
                params.get("end_line"),
            )
            if r.get("status") == "ok":
                return {
                    "success": True,
                    "result": r.get("result", ""),
                    "line_count": len(str(r.get("result", "")).splitlines()),
                }
            return {"success": False, "result": "", "error": r.get("error", "read failed")}

        raw = await handle_batch_read(args, _read_adapter)
        return _normalize_ln_tool_result(raw)

    if name == "batch_grep":

        def _grep_adapter(params: Dict[str, Any]) -> Dict[str, Any]:
            r = _grep_sync(
                params.get("pattern", ""),
                params.get("path"),
                None,
                params.get("context_lines", 2),
                params.get("max_results", 30),
                False,
                "content",
                False,
                None,
                None,
                None,
                0,
                None,
            )
            if r.get("status") != "ok":
                return {"success": False, "matches": [], "error": r.get("error")}
            matches = []
            for item in r.get("result") or []:
                matches.append({
                    "line": item.get("line_num"),
                    "text": item.get("match", ""),
                    "content": item.get("context", ""),
                })
            return {"success": True, "matches": matches, "match_count": len(matches)}

        raw = await handle_batch_grep(args, _grep_adapter)
        return _normalize_ln_tool_result(raw)

    if name == "ssh_exec":
        raw = await handle_ssh_exec(args)
        return _normalize_ln_tool_result(raw)

    async def _ask_user_bridge(q: Dict[str, Any]) -> Dict[str, Any]:
        if send_to_extension is None:
            raise RuntimeError("missing send_to_extension")
        out = await handle_ask_user(
            q,
            send_to_extension,
            timeout=min(int(q.get("timeout_seconds", 300)), 300),
        )
        return {
            "selected": out.get("selected", []),
            "selected_values": out.get("selected", []),
            "skipped": out.get("skipped", False),
            "timed_out": out.get("timed_out", False),
        }

    build_manager = None
    if name in ("git_commit", "git_push", "ssh_deploy"):
        try:
            from app.websocket.versioned_build_manager import VersionedBuildManager

            build_manager = VersionedBuildManager(os.environ.get("CLI_PROJECT_ROOT", "."))
        except Exception:
            build_manager = None

    if name in ("git_commit", "git_push"):
        raw = await handle_git_write(
            {**args, "operation": "commit" if name == "git_commit" else "push"},
            ask_user_fn=_ask_user_bridge if send_to_extension else None,
            build_manager=build_manager,
        )
        return _normalize_ln_tool_result(raw)

    if name == "ssh_deploy":
        raw = await handle_ssh_deploy(
            args,
            ask_user_fn=_ask_user_bridge,
            build_manager=build_manager,
        )
        return _normalize_ln_tool_result(raw)

    return {"status": "error", "error": f"LN tool not implemented: {name}", "error_code": _ERROR_OTHER}


async def execute_tool(
    name: str,
    args: Dict[str, Any],
    cli_type: str = "cloud",
    user_role: str = "ADMIN",
    mode: str = "ask",
    tracker: Optional[DebugInjectionTracker] = None,
    db_pool=None,
    plan_id: Optional[str] = None,
    admin_username: Optional[str] = None,
    workspace_router=None,
    send_to_extension: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
) -> Dict[str, Any]:
    """
    Dispatch a tool call with auth scoping and per-tool timeouts.

    cli_type: "mac" or "cloud"
    user_role: "ADMIN", "COACH", "CLIENT"
    mode: "ask", "plan", "debug", "ln_fab"
    tracker: DebugInjectionTracker for inject_log / debug_cleanup
    db_pool: asyncpg pool for data query tools (Phase 4)
    plan_id: current plan ID for audit logging
    admin_username: admin username for audit logging
    workspace_router: optional callable for routing to VS Code workspace provider
    send_to_extension: async callable to push JSON to the Sovereign IDE client (ask_user, git, deploy).
    """
    _WORKSPACE_ROUTABLE = {
        "read_file", "search_code", "list_directory",
        "read_diagnostics", "read_git_status", "proposed_edit",
        "write_file", "create_file", "delete_file", "rename_file",
        "run_command", "read_open_editors",
    }
    if workspace_router and name in _WORKSPACE_ROUTABLE:
        try:
            ws_result = await workspace_router({"tool": name, "params": args})
            if not ws_result.get("fallback"):
                _ws_error_code = ws_result.get("error_code", "")
                _ws_success = ws_result.get("success", True)
                _RETRIABLE_ERRORS = {"PATH_TRAVERSAL", "FILE_NOT_FOUND", "TIMEOUT"}
                if not _ws_success and _ws_error_code in _RETRIABLE_ERRORS:
                    logger.info("Workspace %s returned %s for %s, falling back to local",
                                name, _ws_error_code, args.get("path", ""))
                else:
                    provider = "vscode_workspace"
                    return {
                        "status": "ok" if _ws_success else "error",
                        "content": ws_result.get("content", ""),
                        "error": ws_result.get("error"),
                        "error_code": ws_result.get("error_code"),
                        "metadata": ws_result.get("metadata", {}),
                        "action": ws_result.get("action"),
                        "provider": provider,
                    }
        except Exception as ws_err:
            logger.warning("Workspace routing failed for %s, falling back to local: %s", name, ws_err)

    if name in _LN_TOOL_NAMES:
        if not _LN_TOOLS_AVAILABLE:
            return {
                "status": "error",
                "error": "LN infrastructure tools are not available in this process.",
                "error_code": _ERROR_OTHER,
            }
        if cli_type != "mac" and name in ("ssh_exec", "git_commit", "git_push", "ssh_deploy"):
            return {
                "status": "error",
                "error": f"Tool '{name}' is only available on CLI-Mac (local workspace + SSH keys).",
                "error_code": _ERROR_PERMISSION_DENIED,
            }
        if name == "ssh_exec" and mode != "debug":
            return {
                "status": "error",
                "error": "ssh_exec is only available in DEBUG mode.",
                "error_code": _ERROR_PERMISSION_DENIED,
            }
        if name in ("git_commit", "git_push", "ssh_deploy"):
            if mode != "ln_fab":
                return {
                    "status": "error",
                    "error": f"'{name}' is only available in LN-FAB mode.",
                    "error_code": _ERROR_PERMISSION_DENIED,
                }
            if name != "ssh_deploy" and send_to_extension is None:
                return {
                    "status": "error",
                    "error": f"'{name}' requires an interactive IDE session (WebSocket UI channel).",
                    "error_code": _ERROR_PERMISSION_DENIED,
                }
        # ssh_deploy on Mac: bypass LN tool handler and forward to Mac agent for SSH key access
        if cli_type == "mac" and name == "ssh_deploy" and _MAC_AGENT_URL:
            try:
                return await asyncio.wait_for(
                    _forward_ssh_deploy_to_mac_agent(args),
                    timeout=MAC_AGENT_HTTP_TIMEOUT,
                )
            except asyncio.TimeoutError:
                return {"status": "error", "error": f"Mac agent ssh_deploy timed out after {MAC_AGENT_HTTP_TIMEOUT}s", "error_code": _ERROR_TIMEOUT}
            except Exception as exc:
                logger.warning("Mac agent ssh_deploy forwarding failed: %s", exc)
                return {"status": "error", "error": f"Mac agent ssh_deploy error: {exc}", "error_code": _ERROR_OTHER}
        if name == "ask_user" and send_to_extension is None:
            return {
                "status": "error",
                "error": "ask_user requires an interactive IDE session to show the prompt.",
                "error_code": _ERROR_PERMISSION_DENIED,
            }

        _ln_timeout = TOOL_TIMEOUTS.get(name, 120)
        try:
            return await asyncio.wait_for(
                _execute_ln_tool(
                    name,
                    args,
                    cli_type=cli_type,
                    mode=mode,
                    send_to_extension=send_to_extension,
                ),
                timeout=_ln_timeout,
            )
        except asyncio.TimeoutError:
            return {
                "status": "error",
                "error": f"Tool '{name}' timed out after {_ln_timeout}s",
                "error_code": _ERROR_TIMEOUT,
            }
        except Exception as exc:
            logger.warning("LN tool %s failed: %s", name, exc)
            return {
                "status": "error",
                "error": f"LN tool error: {exc}",
                "error_code": _ERROR_OTHER,
            }

    if name in _DATA_TOOLS:
        if cli_type == "mac":
            return {"status": "error", "error": "Data query tools are disabled on CLI-Mac (local dev). Use CLI-Cloud.", "error_code": _ERROR_PERMISSION_DENIED}
        if user_role != "ADMIN":
            return {"status": "error", "error": f"Data query tools require ADMIN role. Current role: {user_role}", "error_code": _ERROR_PERMISSION_DENIED}
        if db_pool is None:
            return {"status": "error", "error": "Database pool not available for data queries.", "error_code": _ERROR_OTHER}

        data_handler = _DATA_TOOL_DISPATCH.get(name)
        if data_handler is None:
            return {"status": "error", "error": f"Unknown data tool: {name}", "error_code": _ERROR_OTHER}

        timeout = TOOL_TIMEOUTS.get(name, 10)
        try:
            result = await asyncio.wait_for(
                data_handler(args, db_pool=db_pool),
                timeout=timeout,
            )
            await _log_data_access(db_pool, plan_id, admin_username, name, args, result)
            return result
        except asyncio.TimeoutError:
            return {"status": "error", "error": f"Data query timed out after {timeout}s — try narrower filters", "error_code": _ERROR_TIMEOUT}
        except Exception as exc:
            logger.warning("CLI data tool %s failed: %s", name, exc)
            return {"status": "error", "error": f"Data query error: {exc}", "error_code": _ERROR_OTHER}

    if name in _WRITE_TOOLS:
        if cli_type != "mac":
            return {"status": "error", "error": f"Write tool '{name}' is disabled on CLI-Cloud (production). CLI-Mac only.", "error_code": _ERROR_PERMISSION_DENIED}
        if name == "inject_log" and mode != "debug":
            return {"status": "error", "error": "inject_log is only available in DEBUG mode.", "error_code": _ERROR_PERMISSION_DENIED}

    if name in _SHELL_TOOLS:
        if cli_type != "mac":
            return {"status": "error", "error": "Shell tool is disabled on CLI-Cloud (production). CLI-Mac only.", "error_code": _ERROR_PERMISSION_DENIED}
        if mode not in ("ln_fab", "debug"):
            return {"status": "error", "error": "Shell tool is only available in LN-FAB and DEBUG modes.", "error_code": _ERROR_PERMISSION_DENIED}

    if name in _LINT_TOOLS:
        if cli_type != "mac":
            return {"status": "error", "error": "Lint tool is disabled on CLI-Cloud. CLI-Mac only.", "error_code": _ERROR_PERMISSION_DENIED}

    if name in _NET_TOOLS:
        if cli_type != "mac":
            return {"status": "error", "error": "Web fetch is disabled on CLI-Cloud. CLI-Mac only.", "error_code": _ERROR_PERMISSION_DENIED}

    # Forward CLI-Mac tools to the Mac agent (actual Mac execution, not Docker)
    if cli_type == "mac" and name in _MAC_AGENT_TOOLS and _MAC_AGENT_URL:
        endpoint, payload = _map_tool_to_mac_agent(name, args)
        try:
            if endpoint == "__ssh_deploy__":
                return await asyncio.wait_for(
                    _forward_ssh_deploy_to_mac_agent(payload),
                    timeout=MAC_AGENT_HTTP_TIMEOUT,
                )
            return await asyncio.wait_for(
                _forward_to_mac_agent(endpoint, payload),
                timeout=MAC_AGENT_HTTP_TIMEOUT,
            )
        except asyncio.TimeoutError:
            return {"status": "error", "error": f"Mac agent timed out after {MAC_AGENT_HTTP_TIMEOUT}s", "error_code": _ERROR_TIMEOUT}
        except Exception as exc:
            logger.warning("Mac agent forwarding failed for %s: %s", name, exc)
            return {"status": "error", "error": f"Mac agent error: {exc}", "error_code": _ERROR_OTHER}

    handler = _TOOL_DISPATCH.get(name)
    if handler is None:
        return {"status": "error", "error": f"Unknown tool: {name}", "error_code": _ERROR_OTHER}

    timeout = TOOL_TIMEOUTS.get(name, 5)

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(handler, args, tracker=tracker),
            timeout=timeout,
        )
        return result
    except asyncio.TimeoutError:
        return {
            "status": "error",
            "error": f"Tool timed out after {timeout}s — try a narrower query",
            "error_code": _ERROR_TIMEOUT,
        }
    except Exception as exc:
        logger.warning("CLI tool %s failed: %s", name, exc)
        return {"status": "error", "error": f"Tool execution error: {exc}", "error_code": _ERROR_OTHER}


def get_truncation_limit(mode: str, cli_type: str) -> int:
    return TRUNCATION_LIMITS.get((cli_type, mode), 6000)


def get_tool_definitions(mode: str, cli_type: str) -> list:
    """Build the tools array for native function calling (Grok or Ollama).

    Tool distribution mirrors Cursor's mode capabilities:
    - ASK/PLAN: read + search + grep + glob + read_lints + web_fetch + todo_write + switch_mode
    - LN-FAB:   all of the above + write_file + str_replace + delete_file + shell
    - DEBUG:    all of the above + write_file + str_replace + delete_file + shell + inject_log + debug_cleanup
    """
    tools = list(_READ_TOOL_DEFS)

    _search_tools = [t for t in _PHASE5_TOOL_DEFS if t["function"]["name"] in ("grep", "glob")]
    tools.extend(_search_tools)

    _session_tools = [t for t in _PHASE6_TOOL_DEFS if t["function"]["name"] in ("todo_write", "switch_mode", "provider_stats")]
    tools.extend(_session_tools)

    if _LN_TOOLS_AVAILABLE:
        from app.websocket.tools import (
            ASK_USER_TOOL_DEF as _LNT_ASK,
            BATCH_GREP_TOOL_DEF as _LNT_BG,
            BATCH_READ_TOOL_DEF as _LNT_BR,
            GIT_COMMIT_TOOL_DEF as _LNT_GC,
            GIT_PUSH_TOOL_DEF as _LNT_GP,
            SSH_DEPLOY_TOOL_DEF as _LNT_SD,
            SSH_EXEC_TOOL_DEF as _LNT_SSH,
        )
        tools.append(_wrap_ln_tool_def(_LNT_ASK))
        tools.append(_wrap_ln_tool_def(_LNT_BR))
        tools.append(_wrap_ln_tool_def(_LNT_BG))
        if cli_type == "mac" and mode == "debug":
            tools.append(_wrap_ln_tool_def(_LNT_SSH))
        if cli_type == "mac" and mode == "ln_fab":
            tools.append(_wrap_ln_tool_def(_LNT_GC))
            tools.append(_wrap_ln_tool_def(_LNT_GP))
            tools.append(_wrap_ln_tool_def(_LNT_SD))

    if cli_type == "mac":
        _read_extras = [t for t in _PHASE5_TOOL_DEFS if t["function"]["name"] == "read_lints"]
        tools.extend(_read_extras)

        _fetch_tools = [t for t in _PHASE6_TOOL_DEFS if t["function"]["name"] in ("web_fetch", "web_search_local")]
        tools.extend(_fetch_tools)

        if mode == "ln_fab":
            tools.extend(_WRITE_TOOL_DEFS)
            _fab_tools = [t for t in _PHASE5_TOOL_DEFS if t["function"]["name"] in ("str_replace", "delete_file", "shell")]
            tools.extend(_fab_tools)
            tools.extend(_BUILD_TOOL_DEFS)
            tools = [t for t in tools if t["function"]["name"] not in ("inject_log", "debug_cleanup")]

        elif mode == "debug":
            tools.extend(_WRITE_TOOL_DEFS)
            _debug_tools = [t for t in _PHASE5_TOOL_DEFS if t["function"]["name"] in ("str_replace", "delete_file", "shell")]
            tools.extend(_debug_tools)

    if cli_type == "cloud":
        tools.extend(_DATA_TOOL_DEFS)
        if mode in ("ask", "debug"):
            tools.append({"type": "web_search"})

    return tools


def get_ollama_tool_definitions(mode: str, cli_type: str = "mac") -> list:
    """Build the tools array for Ollama native function calling (Phase 3)."""
    grok_tools = get_tool_definitions(mode, cli_type)
    tools = [{"type": "function", "function": t["function"]} if "function" in t else t for t in grok_tools]
    return tools


def build_ollama_messages(conversation: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Convert the internal conversation format to Ollama's chat API format.

    Phase 3: Ollama supports native function calling via the chat API when
    tools are provided. Tool results go in messages with role="tool".
    This replaces the XML <tool_call> concatenation approach.
    """
    messages = []
    for msg in conversation:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if role == "tool":
            messages.append({
                "role": "tool",
                "content": content,
            })
        elif role in ("system", "user", "assistant"):
            messages.append({"role": role, "content": content})
        else:
            messages.append({"role": "user", "content": content})

    return messages


def extract_ollama_tool_calls(response_data: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Extract tool calls from Ollama's native function calling response.

    Ollama returns tool_calls in the message object when tools are provided:
    {"message": {"role": "assistant", "content": "...", "tool_calls": [...]}}
    """
    msg = response_data.get("message", {})
    tool_calls = msg.get("tool_calls", [])
    if not tool_calls:
        return []

    calls = []
    for tc in tool_calls:
        fn = tc.get("function", {})
        name = fn.get("name", "")
        args = fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (json.JSONDecodeError, TypeError):
                args = {}
        if name:
            calls.append({"name": name, "args": args})
    return calls


def summarize_args(args: Dict[str, Any]) -> str:
    """One-line summary of tool arguments for status messages."""
    if isinstance(args.get("reads"), list):
        return f"batch_read: {len(args['reads'])} files"
    if "question" in args and "options" in args:
        return f"ask_user: {str(args.get('question', ''))[:55]}"
    if args.get("operation") and args.get("server") and "command" not in args:
        return f"ssh_deploy:{args['operation']}@{args['server']}"
    if args.get("server") and args.get("command"):
        return f"ssh:{args['server']}: {args['command'][:60]}"
    if args.get("pattern") and isinstance(args.get("paths"), list):
        return f"batch_grep: /{args['pattern'][:30]}/ ({len(args['paths'])} paths)"
    if "statement" in args:
        return f"inject @ {args.get('path', '?')}:{args.get('line', '?')}: {args['statement'][:60]}"
    if "command" in args:
        desc = args.get("description", "")
        cmd = args["command"][:80]
        return f"{desc}: {cmd}" if desc else cmd
    if "old_string" in args:
        path = args.get("path", "?")
        old = args["old_string"][:40]
        return f"{path}: replace {old!r}..."
    if "url" in args and "path" not in args:
        return f"fetch: {args['url'][:80]}"
    if "todos" in args:
        count = len(args.get("todos", []))
        return f"todos: {count} items"
    if "target_mode" in args:
        return f"switch → {args['target_mode']}: {args.get('explanation', '')[:50]}"
    if "username" in args and "path" not in args:
        return f"user:{args['username']}"
    if "client_id" in args:
        cid = args.get("client_id", "all")
        metric = args.get("metric", "")
        return f"client:{cid} {metric}".strip()
    if "paths" in args and isinstance(args["paths"], list):
        return f"lint: {', '.join(args['paths'][:3])}"
    if "path" in args:
        p = args["path"]
        if "start_line" in args:
            return f"{p}:{args['start_line']}-{args.get('end_line', '?')}"
        if "content" in args:
            return f"{p} ({len(args['content'])} chars)"
        return p
    if "pattern" in args:
        p = args["pattern"]
        g = args.get("glob", "") or args.get("type", "")
        mode = args.get("output_mode", "")
        parts = [f"/{p}/", g, mode]
        return " ".join(x for x in parts if x).strip()
    return json.dumps(args)[:80]

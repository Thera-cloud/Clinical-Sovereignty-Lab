"""
LN Tool Registry — backend/app/websocket/tools/
Sovereign Sanctuary · Little Nate Infrastructure

Central registration hub for all 5 LN tool capabilities.
Import tool definitions and handlers from here.

Capabilities:
  1. ask_user      — Structured user questions (all modes)
  2. batch_tools   — batch_read + batch_grep (all modes)
  3. ssh_tools     — Read-only SSH exec (DEBUG mode)
  4. git_tools     — Git commit/push with safety gates (LN-FAB mode)
  5. ssh_write     — Deploy operations with confirmation (LN-FAB mode)

Usage in cli_tools.py:
    from app.websocket.tools import (
        ALL_MODE_TOOL_DEFS, DEBUG_TOOL_DEFS, FAB_TOOL_DEFS,
        LN_TOOL_NAMES, TOOL_TIMEOUTS, wrap_tool_def_for_ollama,
    )
"""

from .ask_user import (
    ASK_USER_TOOL_DEF,
    handle_ask_user,
    handle_user_response,
    QuestionType,
    StructuredQuestion,
    QuestionResponse,
)

from .batch_tools import (
    BATCH_READ_TOOL_DEF,
    BATCH_GREP_TOOL_DEF,
    handle_batch_read,
    handle_batch_grep,
)

from .ssh_tools import (
    SSH_EXEC_TOOL_DEF,
    handle_ssh_exec,
    execute_ssh,
    validate_command,
    KNOWN_SERVERS,
)

from .git_tools import (
    GIT_COMMIT_TOOL_DEF,
    GIT_PUSH_TOOL_DEF,
    handle_git_write,
    is_read_only,
    is_permanently_blocked,
)

from .ssh_write_tools import (
    SSH_DEPLOY_TOOL_DEF,
    handle_ssh_deploy,
    WRITE_OPERATIONS,
)


# ---------------------------------------------------------------------------
# Tool definition groups by mode
# ---------------------------------------------------------------------------

ALL_MODE_TOOL_DEFS = [
    ASK_USER_TOOL_DEF,
    BATCH_READ_TOOL_DEF,
    BATCH_GREP_TOOL_DEF,
]

DEBUG_TOOL_DEFS = [
    SSH_EXEC_TOOL_DEF,
]

FAB_TOOL_DEFS = [
    GIT_COMMIT_TOOL_DEF,
    GIT_PUSH_TOOL_DEF,
    SSH_DEPLOY_TOOL_DEF,
]

# All definitions combined (for reference/docs)
ALL_TOOL_DEFS = ALL_MODE_TOOL_DEFS + DEBUG_TOOL_DEFS + FAB_TOOL_DEFS

LN_TOOL_NAMES = frozenset(
    {
        "ask_user",
        "batch_read",
        "batch_grep",
        "ssh_exec",
        "git_commit",
        "git_push",
        "ssh_deploy",
    }
)


def wrap_tool_def_for_ollama(defn: dict) -> dict:
    """Convert compact {name, description, parameters} to Ollama/OpenAI tools shape."""
    return {
        "type": "function",
        "function": {
            "name": defn["name"],
            "description": defn["description"],
            "parameters": defn["parameters"],
        },
    }


# ---------------------------------------------------------------------------
# Timeout overrides (seconds) — defaults for each tool
# ---------------------------------------------------------------------------

TOOL_TIMEOUTS = {
    "ask_user": 300,        # 5 min — waiting for human
    "batch_read": 30,
    "batch_grep": 30,
    "ssh_exec": 30,
    "git_commit": 60,
    "git_push": 60,
    "ssh_deploy": 600,      # 10 min — includes wait + verify
}


__all__ = [
    # Capability 1
    "ASK_USER_TOOL_DEF", "handle_ask_user", "handle_user_response",
    "QuestionType", "StructuredQuestion", "QuestionResponse",
    # Capability 2
    "BATCH_READ_TOOL_DEF", "BATCH_GREP_TOOL_DEF",
    "handle_batch_read", "handle_batch_grep",
    # Capability 3
    "SSH_EXEC_TOOL_DEF", "handle_ssh_exec", "execute_ssh",
    "validate_command", "KNOWN_SERVERS",
    # Capability 4
    "GIT_COMMIT_TOOL_DEF", "GIT_PUSH_TOOL_DEF",
    "handle_git_write", "is_read_only", "is_permanently_blocked",
    # Capability 5
    "SSH_DEPLOY_TOOL_DEF", "handle_ssh_deploy", "WRITE_OPERATIONS",
    # Groups
    "ALL_MODE_TOOL_DEFS", "DEBUG_TOOL_DEFS", "FAB_TOOL_DEFS",
    "ALL_TOOL_DEFS", "TOOL_TIMEOUTS", "LN_TOOL_NAMES", "wrap_tool_def_for_ollama",
]

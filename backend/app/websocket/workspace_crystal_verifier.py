"""
Workspace-Verified Crystallization — Phase 6g
Sovereign Sanctuary · Little Nate Infrastructure

When tool calls execute through VS Code's workspace provider (language server,
diagnostics, git API), the results carry higher confidence than local filesystem
execution. This module adds a confidence modifier to the crystal pipeline based
on verification source.

Integration points:
  - cli_tools.py: _cli_log_tool_result() adds workspace_verified field
  - bridge_server.py: nate_cli_chat handler passes verification metadata
  - nate_memory_crystallizer.py: forge_crystal() reads the modifier

File: backend/app/websocket/workspace_crystal_verifier.py
Lines: ~90
Dependencies: None (pure logic, no external packages)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any


class VerificationSource(str, Enum):
    """How a tool call result was obtained."""
    LOCAL_FILESYSTEM = "local"           # Direct file read/write on disk
    WORKSPACE_VSCODE = "vscode_workspace"  # Routed through VS Code extension
    WORKSPACE_VERIFIED = "vscode_verified"  # VS Code + language server validation
    CACHED_R2 = "r2_cache"              # Read from R2 workspace cache (Phase 8)


# Confidence modifiers by verification source.
# These are ADDITIVE to the base confidence set by the crystal pipeline.
# Base confidence for coding domain crystals starts at 0.60 (PROVISIONAL).
# A workspace-verified crystal starts at 0.65 — reaching PROMOTED faster.
CONFIDENCE_MODIFIERS: Dict[VerificationSource, float] = {
    VerificationSource.LOCAL_FILESYSTEM:  0.00,   # No modifier — baseline
    VerificationSource.WORKSPACE_VSCODE:  +0.03,  # VS Code routed, no diagnostics
    VerificationSource.WORKSPACE_VERIFIED: +0.05,  # VS Code + language server confirmed
    VerificationSource.CACHED_R2:         -0.02,  # R2 cache may be stale — slight penalty
}


@dataclass
class ToolCallVerification:
    """Metadata attached to every tool call result for crystal provenance."""
    tool_name: str
    source: VerificationSource = VerificationSource.LOCAL_FILESYSTEM
    workspace_connected: bool = False
    diagnostics_clean: bool = False  # True if VS Code reported 0 errors after edit
    git_tracked: bool = False        # True if file is tracked in git
    duration_ms: int = 0
    error_code: Optional[str] = None

    @property
    def confidence_modifier(self) -> float:
        """Calculate the confidence modifier for crystallization."""
        base = CONFIDENCE_MODIFIERS.get(self.source, 0.0)
        # Bonus if diagnostics confirmed zero errors after a write operation
        if self.diagnostics_clean and self.tool_name in ("write_file", "str_replace"):
            base += 0.02
        return base

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for JSONL logging and crystal metadata."""
        return {
            "tool": self.tool_name,
            "source": self.source.value,
            "workspace_connected": self.workspace_connected,
            "diagnostics_clean": self.diagnostics_clean,
            "git_tracked": self.git_tracked,
            "confidence_modifier": self.confidence_modifier,
            "duration_ms": self.duration_ms,
            "error_code": self.error_code,
        }


def classify_verification(
    tool_name: str,
    workspace_connected: bool,
    routed_through_workspace: bool,
    diagnostics_result: Optional[Dict] = None,
    duration_ms: int = 0,
    error_code: Optional[str] = None,
) -> ToolCallVerification:
    """
    Classify a tool call's verification level based on execution context.

    Called by cli_tools.py after every tool execution, before logging.

    Parameters:
        tool_name: Name of the CLI tool (read_file, str_replace, etc.)
        workspace_connected: Whether VS Code extension is connected
        routed_through_workspace: Whether this specific call went through VS Code
        diagnostics_result: VS Code diagnostics after the operation (if available)
        duration_ms: Execution time in milliseconds
        error_code: Error code if the tool call failed

    Returns:
        ToolCallVerification with source classification and confidence modifier.
    """
    if not workspace_connected:
        source = VerificationSource.LOCAL_FILESYSTEM
    elif routed_through_workspace:
        # Check if diagnostics confirmed the result
        if diagnostics_result and diagnostics_result.get("error_count", 1) == 0:
            source = VerificationSource.WORKSPACE_VERIFIED
        else:
            source = VerificationSource.WORKSPACE_VSCODE
    else:
        # VS Code connected but tool executed locally (fallback path)
        source = VerificationSource.LOCAL_FILESYSTEM

    diagnostics_clean = (
        isinstance(diagnostics_result, dict)
        and diagnostics_result.get("error_count", 1) == 0
    )

    git_tracked = (
        diagnostics_result.get("git_tracked", False)
        if isinstance(diagnostics_result, dict)
        else False
    )

    return ToolCallVerification(
        tool_name=tool_name,
        source=source,
        workspace_connected=workspace_connected,
        diagnostics_clean=diagnostics_clean,
        git_tracked=git_tracked,
        duration_ms=duration_ms,
        error_code=error_code,
    )

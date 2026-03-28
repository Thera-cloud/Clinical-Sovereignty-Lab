"""
Batch Read + Batch Grep — Capability 2
Sovereign Sanctuary · Little Nate Infrastructure

Read up to 20 files in one tool call with a 50k char budget.
Batch grep runs the same pattern across up to 40 files and returns
a structured report. The "audit all 40 auditor files" scenario
becomes one call instead of 40.

File: backend/app/websocket/tools/batch_tools.py
Dependencies: None (uses existing read_file and grep internals)
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# Batch Read
# ---------------------------------------------------------------------------

async def handle_batch_read(
    params: Dict[str, Any],
    read_file_fn: Callable,
    project_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Read multiple files (or file sections) in a single tool call.

    params:
        reads: list of {path, start_line?, end_line?}
        max_total_chars: int (default 50000)
    """
    reads = params.get("reads", [])
    max_total = params.get("max_total_chars", 50_000)

    if not reads:
        return {"success": False, "error": "No reads specified", "error_code": "INVALID_PARAMS"}
    if len(reads) > 20:
        return {"success": False, "error": "Max 20 reads per batch", "error_code": "BATCH_TOO_LARGE"}

    results: List[Dict[str, Any]] = []
    total_chars = 0
    start_time = time.monotonic()

    for i, read_spec in enumerate(reads):
        file_path = read_spec.get("path", "")
        start_line = read_spec.get("start_line")
        end_line = read_spec.get("end_line")

        if not file_path:
            results.append({"path": file_path, "success": False, "error": "Empty path", "index": i})
            continue

        if total_chars >= max_total:
            results.append({
                "path": file_path, "success": False,
                "error": f"Batch char budget exceeded ({max_total})",
                "error_code": "BUDGET_EXCEEDED", "index": i,
            })
            continue

        try:
            read_params: Dict[str, Any] = {"path": file_path}
            if start_line is not None:
                read_params["start_line"] = start_line
            if end_line is not None:
                read_params["end_line"] = end_line

            result = await _call_read(read_file_fn, read_params)
            content = result.get("result", "")
            content_len = len(content)

            remaining = max_total - total_chars
            if content_len > remaining:
                content = content[:remaining] + f"\n... [TRUNCATED — {content_len - remaining} chars omitted]"
                content_len = remaining

            total_chars += content_len
            results.append({
                "path": file_path, "success": result.get("success", True),
                "content": content, "lines": result.get("line_count", 0),
                "start_line": start_line, "end_line": end_line,
                "chars": content_len, "index": i,
            })
        except Exception as e:
            results.append({"path": file_path, "success": False, "error": str(e), "index": i})

    duration_ms = int((time.monotonic() - start_time) * 1000)
    succeeded = sum(1 for r in results if r.get("success"))

    output_parts = [
        f"=== BATCH READ: {succeeded}/{len(reads)} files, {total_chars} chars, {duration_ms}ms ===\n"
    ]
    for r in results:
        if r.get("success"):
            line_info = ""
            if r.get("start_line"):
                line_info = f" (lines {r['start_line']}-{r.get('end_line', 'EOF')})"
            output_parts.append(f"\n--- {r['path']}{line_info} ---")
            output_parts.append(r.get("content", ""))
        else:
            output_parts.append(f"\n--- {r['path']} --- FAILED: {r.get('error', 'unknown')}")

    return {
        "success": succeeded > 0,
        "result": "\n".join(output_parts),
        "files_read": succeeded,
        "files_failed": len(reads) - succeeded,
        "total_chars": total_chars,
        "duration_ms": duration_ms,
    }


async def _call_read(read_fn: Callable, params: Dict) -> Dict:
    result = read_fn(params) if not asyncio.iscoroutinefunction(read_fn) else await read_fn(params)
    if isinstance(result, dict):
        return result
    return {"success": True, "result": str(result)}


# ---------------------------------------------------------------------------
# Batch Grep
# ---------------------------------------------------------------------------

async def handle_batch_grep(
    params: Dict[str, Any],
    grep_fn: Callable,
) -> Dict[str, Any]:
    """
    Run the same grep pattern across multiple file paths.

    params:
        pattern: str — regex pattern
        paths: list of str — file paths or glob patterns
        context_lines: int (default 2)
        max_matches_per_file: int (default 10)
        max_total_matches: int (default 50)
    """
    pattern = params.get("pattern", "")
    paths = params.get("paths", [])
    context = params.get("context_lines", 2)
    max_per_file = params.get("max_matches_per_file", 10)
    max_total = params.get("max_total_matches", 50)

    if not pattern:
        return {"success": False, "error": "No pattern specified", "error_code": "INVALID_PARAMS"}
    if not paths:
        return {"success": False, "error": "No paths specified", "error_code": "INVALID_PARAMS"}
    if len(paths) > 40:
        return {"success": False, "error": "Max 40 paths per batch", "error_code": "BATCH_TOO_LARGE"}

    start_time = time.monotonic()
    all_matches: List[Dict[str, Any]] = []
    total_match_count = 0
    files_with_matches = 0

    for file_path in paths:
        if total_match_count >= max_total:
            break

        try:
            grep_params = {
                "pattern": pattern,
                "path": file_path,
                "context_lines": context,
                "max_results": min(max_per_file, max_total - total_match_count),
            }
            result = grep_fn(grep_params) if not asyncio.iscoroutinefunction(grep_fn) else await grep_fn(grep_params)

            if isinstance(result, dict) and result.get("success"):
                matches = result.get("matches", [])
                match_count = result.get("match_count", len(matches))
                if match_count > 0:
                    files_with_matches += 1
                    total_match_count += match_count
                    all_matches.append({
                        "path": file_path,
                        "match_count": match_count,
                        "matches": matches,
                    })
        except Exception as e:
            all_matches.append({"path": file_path, "match_count": 0, "error": str(e)})

    duration_ms = int((time.monotonic() - start_time) * 1000)

    output_parts = [
        f"=== BATCH GREP: '{pattern}' across {len(paths)} paths ===",
        f"=== {total_match_count} matches in {files_with_matches} files, {duration_ms}ms ===\n",
    ]
    for file_result in all_matches:
        path = file_result["path"]
        count = file_result["match_count"]
        if file_result.get("error"):
            output_parts.append(f"--- {path} --- ERROR: {file_result['error']}")
            continue
        output_parts.append(f"--- {path} ({count} matches) ---")
        for match in file_result.get("matches", []):
            if isinstance(match, dict):
                line_num = match.get("line", "?")
                text = match.get("text", match.get("content", ""))
                output_parts.append(f"  L{line_num}: {text}")
            else:
                output_parts.append(f"  {match}")

    return {
        "success": total_match_count > 0 or files_with_matches == 0,
        "result": "\n".join(output_parts),
        "total_matches": total_match_count,
        "files_with_matches": files_with_matches,
        "files_searched": len(paths),
        "duration_ms": duration_ms,
    }


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

BATCH_READ_TOOL_DEF = {
    "name": "batch_read",
    "description": (
        "Read multiple files or file sections in a single call. "
        "Use when scanning several files for a cross-cutting concern, "
        "auditing multiple auditor files, or reading different sections of a large file. "
        "Max 20 reads per batch, 50k char budget."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "reads": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path relative to workspace root"},
                        "start_line": {"type": "integer", "description": "First line to read (1-based)"},
                        "end_line": {"type": "integer", "description": "Last line to read (inclusive)"},
                    },
                    "required": ["path"],
                },
                "description": "List of file reads to perform",
            },
            "max_total_chars": {
                "type": "integer",
                "description": "Max total characters across all reads (default 50000)",
                "default": 50000,
            },
        },
        "required": ["reads"],
    },
}

BATCH_GREP_TOOL_DEF = {
    "name": "batch_grep",
    "description": (
        "Search for a pattern across multiple files in a single call. "
        "Use when auditing multiple files for the same pattern — e.g., checking "
        "TAB_ENDPOINTS in all auditor files, finding all imports of a module. "
        "Max 40 paths per batch."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern to search for"},
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of file paths or glob patterns to search",
            },
            "context_lines": {
                "type": "integer",
                "description": "Lines of context around each match (default 2)",
                "default": 2,
            },
            "max_matches_per_file": {
                "type": "integer",
                "description": "Max matches to return per file (default 10)",
                "default": 10,
            },
            "max_total_matches": {
                "type": "integer",
                "description": "Cap total matches across all files (default 50)",
                "default": 50,
            },
        },
        "required": ["pattern", "paths"],
    },
}

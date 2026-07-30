"""W14 / R3: GitHub App opens draft PRs against frozen-config only.

Cannot merge; cannot push main. Uses GITHUB_APP_* or gh CLI when available.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("sovereign_weld_bot")

APP_NAME = "sovereign-weld-bot"


def open_shadow_eval_pr(
    *,
    title: str,
    body: str,
    branch: str,
    files: Dict[str, str],
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Open a PR with proposed frozen-config diffs. Default dry_run=True."""
    if not files:
        return {"ok": False, "error": "no_files"}
    # Only allow paths under frozen-config/
    for rel in files:
        if not str(rel).startswith("frozen-config/"):
            return {"ok": False, "error": "path_outside_frozen_config", "path": rel}

    if dry_run or os.getenv("SOVEREIGN_WELD_BOT_DRY_RUN", "1") not in (
        "0", "false", "False",
    ):
        return {
            "ok": True,
            "dry_run": True,
            "app": APP_NAME,
            "branch": branch,
            "title": title,
            "files": list(files.keys()),
            "note": "PR not opened (dry_run). Set SOVEREIGN_WELD_BOT_DRY_RUN=0 to enable.",
        }

    repo = os.getenv("GITHUB_REPOSITORY", "Thera-cloud/Clinical-Sovereignty-Lab")
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for rel, content in files.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            # Prefer gh pr create from a worktree when credentials exist
            meta = root / "pr_meta.json"
            meta.write_text(
                json.dumps({"title": title, "body": body, "branch": branch}),
                encoding="utf-8",
            )
            proc = subprocess.run(
                [
                    "gh", "pr", "create",
                    "--repo", repo,
                    "--title", title,
                    "--body", body,
                    "--draft",
                    "--head", branch,
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            return {
                "ok": proc.returncode == 0,
                "app": APP_NAME,
                "stdout": (proc.stdout or "")[:1000],
                "stderr": (proc.stderr or "")[:1000],
            }
    except FileNotFoundError:
        return {"ok": False, "error": "gh_cli_missing", "app": APP_NAME}
    except Exception as e:
        logger.warning("open_shadow_eval_pr failed: %s", e)
        return {"ok": False, "error": str(e), "app": APP_NAME}

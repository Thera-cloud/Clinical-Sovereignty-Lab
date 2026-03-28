#!/usr/bin/env python3
"""
Fail if nate_cli_chat workspace rules would omit rules or clip mid-block
at DEFAULT_CLI_RULES_MAX_CHARS (must match bridge / cli_manifest default).

Run from repo root:
  PYTHONPATH=backend python3 scripts/check_cli_workspace_rules_budget.py
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    backend_dir = os.path.join(repo_root, "backend")
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    from app.websocket.cli_manifest import (  # noqa: E402
        DEFAULT_CLI_RULES_MAX_CHARS,
        audit_workspace_rules_budget,
    )

    errors = audit_workspace_rules_budget(
        root=repo_root,
        max_total_chars=DEFAULT_CLI_RULES_MAX_CHARS,
    )
    if errors:
        print("CLI workspace rules budget failures:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print(
            "\nRemediation: shorten rules, trim _MODE_RULES in cli_manifest.py, "
            "or raise DEFAULT_CLI_RULES_MAX_CHARS (update bridge default + this check).",
            file=sys.stderr,
        )
        return 1
    print(
        f"OK: ask/plan/ln_fab/debug rules within cap ({DEFAULT_CLI_RULES_MAX_CHARS} chars on rule bodies)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

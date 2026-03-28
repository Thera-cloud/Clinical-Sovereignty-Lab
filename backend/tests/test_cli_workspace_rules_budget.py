"""
nate_cli_chat injects WORKSPACE RULES via cli_manifest.load_workspace_rules.

CI must fail if the assembled rules hit the total-char cap (omitted rules or
\"budget exceeded\" mid-block). Cap is DEFAULT_CLI_RULES_MAX_CHARS — keep in
sync with bridge defaults and scripts/check_cli_workspace_rules_budget.py.
"""

import os


def test_cli_workspace_rules_budget_healthy():
    from app.websocket.cli_manifest import (
        DEFAULT_CLI_RULES_MAX_CHARS,
        audit_workspace_rules_budget,
    )

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    errors = audit_workspace_rules_budget(
        root=repo_root,
        max_total_chars=DEFAULT_CLI_RULES_MAX_CHARS,
    )
    assert not errors, ";\n".join(errors)

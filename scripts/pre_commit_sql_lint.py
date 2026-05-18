#!/usr/bin/env python3
"""Pre-commit guard: catch known SQL column-name bugs before they ship.

NARROW SCOPE — flags only patterns that are SQL bugs in this codebase.
False-positive tolerant: only triggers when a banned token appears on a line
that also contains an SQL verb, OR appears inside a triple-quoted SQL string.

Banned tokens (column names that DO NOT EXIST in the production schema but
have caused live failures previously):
  - cancelled_at         (subscriptions table uses canceled_at, one 'L')
  - payment_history columns: username, description, payment_type, product_id, source
    (real schema is user_id UUID, event_type, failure_reason, metadata)

Usage:
  - As a git pre-commit hook: scripts/install_pre_commit_hook.sh
  - Manually:                  python3 scripts/pre_commit_sql_lint.py
  - On full tree (not staged): python3 scripts/pre_commit_sql_lint.py --all
"""
from __future__ import annotations
import re
import sys
import subprocess
from pathlib import Path

SQL_VERB_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|SELECT|FROM|WHERE|SET|VALUES|RETURNING|JOIN)\b",
    re.IGNORECASE,
)

# Production schema audit (verified 2026-05-18 against little_nate):
#   subscriptions.canceled_at         (American, one 'L')   <-- canonical
#   staged_deletions.cancelled_at     (British, legitimate)
#   detector_auto_disable_state.cancelled_at  (British, legitimate)
# So `cancelled_at` is only a bug when the SQL targets `subscriptions`.
WINDOW_LINES = 6  # span of SQL across newlines we will look at

# payment_history columns that don't exist in the real schema.
# Trigger when these appear in the column list of an INSERT INTO payment_history.
PH_BAD_COLS = {"username", "description", "payment_type", "product_id", "source"}
PH_TARGET_RE = re.compile(
    r"INSERT\s+INTO\s+payment_history\s*\(([^)]+)\)",
    re.IGNORECASE | re.DOTALL,
)

# Bare identifier only — must NOT be preceded by a quote (rules out Python
# dict subscripts like sub["cancelled_at"] and JSON keys like "cancelled_at":).
CANCELLED_RE = re.compile(r"(?<![\"'])\bcancelled_at\b(?![\"'])")
SUBS_TABLE_RE = re.compile(r"\bsubscriptions\b")
# Self-exclude: this linter inevitably mentions its own targets.
SELF_SKIP = {"scripts/pre_commit_sql_lint.py"}


def _staged_files() -> list[str]:
    try:
        out = subprocess.check_output(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            text=True,
        )
        return [f for f in out.splitlines() if f.endswith(".py")]
    except subprocess.CalledProcessError:
        return []


EXCLUDED_PREFIXES = ("archive/", "backups/", ".venv/", "node_modules/")


def _all_files() -> list[str]:
    root = Path.cwd()
    out: list[str] = []
    for p in root.rglob("*.py"):
        rel = str(p.relative_to(root))
        if any(rel.startswith(pref) or f"/{pref[:-1]}/" in f"/{rel}" for pref in EXCLUDED_PREFIXES):
            continue
        out.append(rel)
    return out


def scan_file(path: str) -> list[str]:
    """Return list of human-readable violation messages for one file."""
    failures: list[str] = []
    if path in SELF_SKIP:
        return failures
    try:
        text = Path(path).read_text()
    except (OSError, UnicodeDecodeError):
        return failures

    lines = text.splitlines()

    # 1. cancelled_at in SQL targeting the `subscriptions` table only.
    # The bug is `UPDATE subscriptions SET ..., cancelled_at = NOW()` where
    # `subscriptions` and `cancelled_at` may appear on adjacent lines.
    for i, line in enumerate(lines, start=1):
        if not CANCELLED_RE.search(line):
            continue
        lo = max(0, i - WINDOW_LINES)
        hi = min(len(lines), i + WINDOW_LINES)
        window = "\n".join(lines[lo:hi])
        if SUBS_TABLE_RE.search(window) and SQL_VERB_RE.search(window):
            failures.append(
                f"{path}:{i}: 'cancelled_at' in SQL referencing 'subscriptions' — "
                "subscriptions table column is canceled_at (American spelling, one 'L'). "
                "Other tables (staged_deletions, detector_auto_disable_state) "
                "legitimately use cancelled_at."
            )

    # 2. Whole-file scan: INSERT INTO payment_history with banned columns.
    for m in PH_TARGET_RE.finditer(text):
        col_list = m.group(1)
        cols = {c.strip().lower() for c in re.split(r"[,\s]+", col_list) if c.strip()}
        bad_present = cols & PH_BAD_COLS
        if bad_present:
            line_no = text[: m.start()].count("\n") + 1
            failures.append(
                f"{path}:{line_no}: INSERT INTO payment_history uses non-existent "
                f"column(s) {sorted(bad_present)} — real columns include "
                f"user_id (UUID FK), amount_cents, currency, status, event_type, "
                f"failure_reason, metadata"
            )

    return failures


def main() -> int:
    if "--all" in sys.argv:
        files = _all_files()
    else:
        files = _staged_files()

    if not files:
        return 0

    all_failures: list[str] = []
    for f in files:
        all_failures.extend(scan_file(f))

    if all_failures:
        print("PRE-COMMIT SQL LINT FAILED", file=sys.stderr)
        print("(see .cursor/rules/sql-schema-verification.mdc for schema reference)\n",
              file=sys.stderr)
        for msg in all_failures:
            print(f"  {msg}", file=sys.stderr)
        print(
            f"\n{len(all_failures)} violation(s). "
            "Fix the SQL or `git commit --no-verify` to override.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

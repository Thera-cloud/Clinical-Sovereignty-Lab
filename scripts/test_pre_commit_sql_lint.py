#!/usr/bin/env python3
"""Self-test for pre_commit_sql_lint.py — run after changes to the linter."""
from __future__ import annotations
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
from pre_commit_sql_lint import scan_file  # noqa: E402


def _write(text: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".py")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    return path


CASES = [
    (
        "catches cancelled_at in subscriptions UPDATE",
        '''
async def cancel():
    await db.execute(
        """UPDATE subscriptions SET status = 'CANCELLED',
           cancelled_at = NOW() WHERE user_id = $1""",
        uid,
    )
''',
        True,
        "cancelled_at",
    ),
    (
        "ignores cancelled_at in staged_deletions",
        '''
async def cancel_deletion():
    await db.execute(
        """UPDATE staged_deletions SET cancelled = TRUE,
           cancelled_at = NOW() WHERE id = $1""",
        did,
    )
''',
        False,
        None,
    ),
    (
        "ignores cancelled_at in detector_auto_disable_state SELECT",
        '''
async def fetch():
    row = await conn.fetchrow(
        """SELECT state, armed_at, cancelled_at
           FROM detector_auto_disable_state WHERE gap_flag = $1""",
        gap,
    )
''',
        False,
        None,
    ),
    (
        "ignores Python dict-key cancelled_at",
        '''
async def update_billing():
    sub = await db.fetchrow("SELECT * FROM subscriptions WHERE user_id = $1", uid)
    sub["cancelled_at"] = "now"
''',
        False,
        None,
    ),
    (
        "catches payment_history INSERT with banned columns",
        '''
async def refund():
    await db.execute(
        """INSERT INTO payment_history
           (username, amount, currency, status, description, metadata, created_at)
           VALUES ($1, $2, 'usd', 'refunded', $3, $4::jsonb, NOW())""",
        uid, amt, reason, meta,
    )
''',
        True,
        "payment_history",
    ),
    (
        "ignores correct payment_history INSERT",
        '''
async def refund():
    await db.execute(
        """INSERT INTO payment_history
           (user_id, amount_cents, currency, status, event_type, metadata, created_at)
           VALUES ($1, $2, 'usd', 'refunded', 'admin_refund', $3::jsonb, NOW())""",
        uid, cents, meta,
    )
''',
        False,
        None,
    ),
]


def main() -> int:
    failed = 0
    for desc, body, should_fire, must_contain in CASES:
        path = _write(body)
        try:
            violations = scan_file(path)
            fired = len(violations) > 0
            if fired != should_fire:
                print(f"FAIL: {desc} — expected fire={should_fire}, got {violations}")
                failed += 1
                continue
            if should_fire and not any(must_contain in v for v in violations):
                print(f"FAIL: {desc} — expected '{must_contain}' in violations, got {violations}")
                failed += 1
                continue
            print(f"PASS: {desc}")
        finally:
            os.unlink(path)
    print()
    if failed:
        print(f"{failed} TEST(S) FAILED")
        return 1
    print(f"ALL {len(CASES)} LINTER TESTS PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

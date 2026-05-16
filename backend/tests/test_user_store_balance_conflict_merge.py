"""
Mirrors bridge UserStore upsert balance CASE (profile sync).
Must stay aligned with backend/app/websocket/user_store.py ON CONFLICT.
"""
from typing import Optional


def merge_token_column(users_val: Optional[int], excluded_val: Optional[int]) -> int:
    u = users_val if users_val is not None else 0
    e = excluded_val if excluded_val is not None else 0
    if u == 0 and e > 0:
        return int(excluded_val)
    first = users_val if users_val is not None else None
    if first is None:
        first = excluded_val if excluded_val is not None else None
    return int(first if first is not None else 0)


def test_stuck_db_zero_bridge_has_trial_grant():
    assert merge_token_column(0, 10_000) == 10_000


def test_existing_nonzero_preserved_over_bridge_lower():
    assert merge_token_column(5_000, 3_000) == 5_000


def test_legitimately_spent_all_zero():
    assert merge_token_column(0, 0) == 0


def test_db_null_bridge_has_grant():
    assert merge_token_column(None, 10_000) == 10_000

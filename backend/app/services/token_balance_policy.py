"""
Subscription vs purchased token buckets — deduction order and balance sync.

Purchased tokens are consumed first; then subscription tokens.
token_balance must always equal subscription_token_balance + purchased_token_balance.
"""

from __future__ import annotations


def split_balances_from_profile(profile: dict) -> tuple[int, int]:
    """Return (subscription_part, purchased_part) from cache profile."""
    purch = int(profile.get("purchased_token_balance") or 0)
    sub = profile.get("subscription_token_balance")
    if sub is None:
        total = int(profile.get("token_balance") or 0)
        sub = max(0, total - purch)
    else:
        sub = int(sub or 0)
    return sub, purch


def apply_deduction(sub: int, purch: int, amount: int) -> tuple[int, int]:
    """Deduct amount from purchased first, then subscription. Returns (new_sub, new_purch)."""
    if amount <= 0:
        return sub, purch
    use_p = min(purch, amount)
    remaining = amount - use_p
    new_p = purch - use_p
    use_s = min(sub, remaining)
    new_s = sub - use_s
    return max(0, new_s), max(0, new_p)


def total_balance(sub: int, purch: int) -> int:
    return max(0, int(sub or 0)) + max(0, int(purch or 0))

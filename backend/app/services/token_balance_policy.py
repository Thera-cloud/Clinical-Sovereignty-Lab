"""
Subscription vs purchased token buckets — deduction order and balance sync.

Purchased tokens are consumed first; then subscription tokens.
token_balance must always equal subscription_token_balance + purchased_token_balance.
"""

from __future__ import annotations


def split_balances_from_profile(profile: dict) -> tuple[int, int]:
    """Return (subscription_part, purchased_part) from cache profile."""
    purch = int(profile.get("purchased_token_balance") or 0)
    sub_raw = profile.get("subscription_token_balance")
    canonical_total = int(profile.get("token_balance") or 0)

    if sub_raw is None:
        sub = max(0, canonical_total - purch)
    else:
        sub = int(sub_raw or 0)

    bucket_total = sub + purch
    # token_balance is authoritative when buckets drift (Token Lab / SQL grants often
    # bump token_balance without rewriting subscription_/purchased_ columns).
    if canonical_total > bucket_total:
        sub += canonical_total - bucket_total
    elif canonical_total < bucket_total:
        rem = max(0, canonical_total)
        new_purch = min(purch, rem)
        rem -= new_purch
        sub = rem
        purch = new_purch

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

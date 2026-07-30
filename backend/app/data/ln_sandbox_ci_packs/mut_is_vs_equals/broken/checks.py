def is_zero(x) -> bool:
    # BUG: 'is' checks identity, not value equality
    return x is 0

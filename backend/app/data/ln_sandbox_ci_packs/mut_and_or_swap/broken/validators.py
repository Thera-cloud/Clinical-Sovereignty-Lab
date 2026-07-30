def is_valid_age(age: int) -> bool:
    # BUG: should require BOTH bounds, uses 'or' instead of 'and'
    return age >= 0 or age <= 120

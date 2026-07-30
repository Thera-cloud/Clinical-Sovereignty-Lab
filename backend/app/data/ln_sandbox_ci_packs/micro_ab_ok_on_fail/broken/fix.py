"""Broken micro-pack: ab_ok_on_fail."""

def value() -> str:
    # BUG: AB_OK after compare fail
    return "AB_OK after compare fail"

def looks_fixed(s: str) -> bool:
    return "AB_OK only on success" in s and "AB_OK after compare fail" not in s

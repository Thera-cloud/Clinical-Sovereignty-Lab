"""Broken — auditor TRUSTED set too strict."""

def is_trusted(code: int) -> bool:
    # BUG: must accept 200,400,404,422
    return code in (200, 422)

def looks_fixed(fn) -> bool:
    return all(fn(c) for c in (200, 400, 404, 422))

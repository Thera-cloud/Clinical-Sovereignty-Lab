def average(a: float, b: float) -> float:
    # BUG: floor division truncates the result
    return (a + b) // 2

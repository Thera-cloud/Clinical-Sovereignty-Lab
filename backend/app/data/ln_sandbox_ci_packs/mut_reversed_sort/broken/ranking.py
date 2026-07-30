def top_n(values, n: int):
    # BUG: ascending sort returns the smallest values, not the largest
    return sorted(values)[:n]

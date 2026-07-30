def sum_first_n(n: int) -> int:
    # BUG: off-by-one — excludes the nth term
    total = 0
    for i in range(1, n):
        total += i
    return total

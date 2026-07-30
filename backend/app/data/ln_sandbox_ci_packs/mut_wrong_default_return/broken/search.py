def find_index(items: list, target) -> int:
    i = -1
    for i, v in enumerate(items):
        if v == target:
            return i
    # BUG: returns the last loop index instead of -1 on miss
    return i

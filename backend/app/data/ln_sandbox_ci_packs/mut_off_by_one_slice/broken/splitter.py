def first_half(items: list) -> list:
    # BUG: drops the middle element on odd-length input
    return items[: len(items) // 2 - 1]

def append_item(item, items=[]):
    # BUG: mutable default arg is shared across calls
    items.append(item)
    return items

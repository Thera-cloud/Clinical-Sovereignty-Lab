def safe_div(a: float, b: float):
    # BUG: catches the wrong exception type
    try:
        return a / b
    except TypeError:
        return None

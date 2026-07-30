def clean_name(name: str) -> str:
    # BUG: leaves leading/trailing whitespace in place
    return name.lower()

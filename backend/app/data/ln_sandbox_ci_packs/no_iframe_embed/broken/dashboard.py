"""Broken — Hive Defense must not use iframe."""

def embed_hive() -> str:
    # BUG: iframe blocked by X-Frame-Options
    return '<iframe src="hive_defense.html"></iframe>'

def looks_fixed(html: str) -> bool:
    return "iframe" not in html and "tab-hive" in html

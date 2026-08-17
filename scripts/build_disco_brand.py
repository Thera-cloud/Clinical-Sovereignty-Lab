#!/usr/bin/env python3
"""Write T1.MIG brand SSR files into public/disco/brand/site/."""

from __future__ import annotations

import shutil
from pathlib import Path

from app.services.disco.assets import BRAND_ROBOTS
from app.services.disco.brand import (
    PAGES,
    TEST_COACH,
    render_brand_page,
    render_hub_page,
    render_metro_page,
    sitemap_xml,
)
from app.services.disco.renderer import render_profile_html

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "public" / "disco" / "brand" / "site"
SRC = ROOT / "public" / "disco" / "brand"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    for path in PAGES:
        html = render_brand_page(path)
        dest = OUT / "index.html" if path == "/" else OUT / path.strip("/") / "index.html"
        _write(dest, html)
    _write(OUT / "metros" / "detroit" / "index.html", render_metro_page("Detroit", "coachn"))
    _write(OUT / "hubs" / "family-systems" / "index.html", render_hub_page("family-systems", "coachn"))
    coach = render_profile_html(TEST_COACH, relationship_class="coaching")
    if coach.get("blocked"):
        raise SystemExit(coach.get("lint"))
    _write(OUT / "coaches" / "coachn" / "index.html", coach["html"])
    _write(OUT / "sitemap.xml", sitemap_xml())
    _write(OUT / "robots.txt", BRAND_ROBOTS)
    shutil.copy2(SRC / "BingSiteAuth.xml", OUT / "BingSiteAuth.xml")
    key = SRC / "30f24e0be266373675ca6d01227d0ff1.txt"
    if key.exists():
        shutil.copy2(key, OUT / key.name)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

"""Publish / unpublish blog HTML under public_site → /var/www/sovereign-public.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nate.growth.blog_publisher")

PUBLIC_SITE_ROOT = Path(
    os.getenv(
        "GROWTH_PUBLIC_SITE_ROOT",
        str(Path(__file__).resolve().parents[4] / "public_site"),
    )
)
DEPLOY_ROOT = Path(
    os.getenv("GROWTH_PUBLIC_DEPLOY_ROOT", "/var/www/sovereign-public")
)


def _slugify(title: str, fallback: str = "article") -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return s[:80] or fallback


def render_article_html(
    *,
    title: str,
    body_html: str,
    slug: str,
    published_at: Optional[str] = None,
    canonical_base: str = "https://app.sovereignsanctuary.net",
) -> str:
    pub = published_at or datetime.now(timezone.utc).isoformat()
    canonical = f"{canonical_base.rstrip('/')}/blog/{slug}.html"
    safe_title = html.escape(title or "Article")
    json_ld = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "datePublished": pub,
        "author": {"@type": "Organization", "name": "Sovereign Sanctuary"},
        "mainEntityOfPage": canonical,
    }
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{safe_title} — Sovereign Sanctuary</title>
<link rel="canonical" href="{html.escape(canonical)}"/>
<meta name="robots" content="index,follow"/>
<style>
body{{margin:0;font-family:'DM Sans',system-ui,sans-serif;background:#050505;color:#E8E4DC;line-height:1.65}}
main{{max-width:720px;margin:0 auto;padding:48px 20px}}
h1{{font-family:'Cormorant Garamond',Georgia,serif;color:#C9A962;font-weight:500;font-size:2.2rem}}
a{{color:#4ECDC4}}
.footer{{margin-top:3rem;font-size:.85rem;color:#8B7355}}
</style>
<script type="application/ld+json">{json.dumps(json_ld)}</script>
</head>
<body>
<main>
<article>
<h1>{safe_title}</h1>
{body_html}
</article>
<p class="footer">Educational content only — not medical advice. Crisis: 988 (US).</p>
</main>
</body>
</html>
"""


def body_to_html(draft_body: str) -> str:
    """Minimal markdown-ish → HTML (paragraphs + newlines)."""
    text = (draft_body or "").strip()
    if not text:
        return "<p></p>"
    if "<p>" in text or "<h" in text:
        return text
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return "\n".join(f"<p>{html.escape(p).replace(chr(10), '<br/>')}</p>" for p in parts)


def write_article_local(
    *,
    title: str,
    draft_body: str,
    slug: Optional[str] = None,
) -> Dict[str, Any]:
    slug = slug or _slugify(title)
    html_body = body_to_html(draft_body)
    rendered = render_article_html(title=title, body_html=html_body, slug=slug)
    blog_dir = PUBLIC_SITE_ROOT / "blog"
    blog_dir.mkdir(parents=True, exist_ok=True)
    path = blog_dir / f"{slug}.html"
    path.write_text(rendered, encoding="utf-8")
    return {
        "ok": True,
        "slug": slug,
        "local_path": str(path),
        "public_path": f"/blog/{slug}.html",
        "html_body": html_body,
    }


def unpublish_local(slug: str) -> Dict[str, Any]:
    path = PUBLIC_SITE_ROOT / "blog" / f"{slug}.html"
    if path.exists():
        path.unlink()
        return {"ok": True, "removed": str(path)}
    return {"ok": True, "removed": None, "note": "file_absent"}


def regenerate_sitemap(entries: Optional[List[Dict[str, str]]] = None) -> str:
    """Write robots.txt + sitemap.xml under public_site/."""
    PUBLIC_SITE_ROOT.mkdir(parents=True, exist_ok=True)
    robots = PUBLIC_SITE_ROOT / "robots.txt"
    robots.write_text(
        "User-agent: *\nAllow: /\nSitemap: https://app.sovereignsanctuary.net/sitemap.xml\n",
        encoding="utf-8",
    )
    if entries is None:
        entries = []
        blog = PUBLIC_SITE_ROOT / "blog"
        if blog.is_dir():
            for f in sorted(blog.glob("*.html")):
                entries.append(
                    {
                        "loc": f"https://app.sovereignsanctuary.net/blog/{f.name}",
                        "lastmod": datetime.now(timezone.utc).date().isoformat(),
                    }
                )
    urls = "\n".join(
        f"  <url><loc>{html.escape(e['loc'])}</loc>"
        f"<lastmod>{html.escape(e.get('lastmod', ''))}</lastmod></url>"
        for e in entries
    )
    sitemap = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{urls}
</urlset>
"""
    (PUBLIC_SITE_ROOT / "sitemap.xml").write_text(sitemap, encoding="utf-8")
    return str(PUBLIC_SITE_ROOT / "sitemap.xml")

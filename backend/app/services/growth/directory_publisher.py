"""Static coach directory pages under public_site/providers/{slug}.html.

Dual gate: consent_public + admin directory_published.
Withdrawal → 410 page + sitemap regen.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import html
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.growth.blog_publisher import (
    DEPLOY_ROOT,
    PUBLIC_SITE_ROOT,
    body_to_html,
    regenerate_sitemap,
)

logger = logging.getLogger("nate.growth.directory")

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,78}[a-z0-9]$")


def validate_slug(slug: str) -> str:
    s = (slug or "").strip().lower()
    if not _SLUG_RE.match(s):
        raise ValueError("invalid public_slug (use lowercase letters, numbers, hyphens)")
    return s


def render_provider_html(
    *,
    display_name: str,
    seo_bio_md: str,
    slug: str,
    specialty_tags: Optional[List[str]] = None,
    city: Optional[str] = None,
) -> str:
    safe_name = html.escape(display_name or "Coach")
    bio_html = body_to_html(seo_bio_md or "")
    tags = specialty_tags or []
    tags_html = " · ".join(html.escape(str(t)) for t in tags[:12])
    loc = html.escape(city or "")
    signup = (
        f"https://app.sovereignsanctuary.net/?provider={html.escape(slug)}"
        f"&src=directory"
    )
    canonical = f"https://app.sovereignsanctuary.net/providers/{html.escape(slug)}.html"
    json_ld = {
        "@context": "https://schema.org",
        "@type": "Person",
        "name": display_name,
        "description": (seo_bio_md or "")[:500],
        "url": canonical,
    }
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{safe_name} — Sovereign Sanctuary</title>
<link rel="canonical" href="{canonical}"/>
<meta name="robots" content="index,follow"/>
<style>
body{{margin:0;font-family:'DM Sans',system-ui,sans-serif;background:#050505;color:#E8E4DC;line-height:1.65}}
main{{max-width:720px;margin:0 auto;padding:48px 20px}}
h1{{font-family:'Cormorant Garamond',Georgia,serif;color:#C9A962;font-weight:500;font-size:2.2rem}}
.meta{{color:#8B7355;font-size:.9rem;margin-bottom:1.5rem}}
a.cta{{display:inline-block;margin-top:1.5rem;padding:.75rem 1.25rem;background:#C9A962;color:#111;text-decoration:none;border-radius:6px;font-weight:600}}
.footer{{margin-top:3rem;font-size:.85rem;color:#8B7355}}
</style>
<script type="application/ld+json">{json.dumps(json_ld)}</script>
<script>
(function(){{
  try {{
    var API = location.hostname.includes('sovereignsanctuary')
      ? 'https://api.sovereignsanctuary.net' : (localStorage.getItem('sc_api')||'http://localhost:8000');
    fetch(API+'/api/analytics/hit',{{method:'POST',headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{stage:'impression',content_kind:'directory',provider_slug:'{html.escape(slug)}',source:'directory_page'}})}});
  }} catch(e){{}}
}})();
</script>
</head>
<body>
<main>
<article>
<h1>{safe_name}</h1>
<p class="meta">{tags_html}{" · " + loc if loc else ""}</p>
{bio_html}
<a class="cta" href="{signup}" onclick="try{{fetch((location.hostname.includes('sovereignsanctuary')?'https://api.sovereignsanctuary.net':(localStorage.getItem('sc_api')||'http://localhost:8000'))+'/api/analytics/hit',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{stage:'click',content_kind:'directory',provider_slug:'{html.escape(slug)}',source:'directory_cta'}})}});}}catch(e){{}}">Connect on Sanctuary</a>
</article>
<p class="footer">Directory listing — educational discovery only. Not a medical referral. Crisis: 988 (US).</p>
</main>
</body>
</html>
"""


def render_gone_html(slug: str) -> str:
    safe = html.escape(slug)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>Listing withdrawn</title>
<meta name="robots" content="noindex"/>
</head>
<body style="font-family:system-ui;background:#050505;color:#E8E4DC;padding:3rem">
<h1>410 — Listing withdrawn</h1>
<p>The directory page for <code>{safe}</code> is no longer published.</p>
</body></html>
"""


def write_provider_page(
    *,
    display_name: str,
    seo_bio_md: str,
    slug: str,
    specialty_tags: Optional[List[str]] = None,
    city: Optional[str] = None,
) -> Dict[str, Any]:
    slug = validate_slug(slug)
    rendered = render_provider_html(
        display_name=display_name,
        seo_bio_md=seo_bio_md,
        slug=slug,
        specialty_tags=specialty_tags,
        city=city,
    )
    out_dir = PUBLIC_SITE_ROOT / "providers"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{slug}.html"
    path.write_text(rendered, encoding="utf-8")
    _try_deploy_copy(path)
    return {
        "ok": True,
        "slug": slug,
        "local_path": str(path),
        "public_path": f"/providers/{slug}.html",
    }


def withdraw_provider_page(slug: str) -> Dict[str, Any]:
    slug = validate_slug(slug)
    out_dir = PUBLIC_SITE_ROOT / "providers"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{slug}.html"
    path.write_text(render_gone_html(slug), encoding="utf-8")
    _try_deploy_copy(path)
    return {"ok": True, "slug": slug, "status": "410", "path": str(path)}


def _try_deploy_copy(src: Path) -> None:
    try:
        dest_dir = DEPLOY_ROOT / "providers"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    except Exception as e:
        logger.info("directory deploy copy skipped: %s", e)


def regenerate_directory_sitemap() -> str:
    entries: List[Dict[str, str]] = []
    blog = PUBLIC_SITE_ROOT / "blog"
    if blog.is_dir():
        for f in sorted(blog.glob("*.html")):
            entries.append(
                {
                    "loc": f"https://app.sovereignsanctuary.net/blog/{f.name}",
                    "lastmod": datetime.now(timezone.utc).date().isoformat(),
                }
            )
    providers = PUBLIC_SITE_ROOT / "providers"
    if providers.is_dir():
        for f in sorted(providers.glob("*.html")):
            if f.name == "index.html":
                continue
            text = f.read_text(encoding="utf-8", errors="ignore")
            if "410 — Listing withdrawn" in text:
                continue
            entries.append(
                {
                    "loc": f"https://app.sovereignsanctuary.net/providers/{f.name}",
                    "lastmod": datetime.now(timezone.utc).date().isoformat(),
                }
            )
    return regenerate_sitemap(entries)


async def approve_and_publish(db_pool, coach_user_id: str, *, actor: str = "admin") -> Dict[str, Any]:
    """Admin dual-gate publish after consent_public + public_slug set."""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM coach_profiles WHERE coach_user_id = $1",
            coach_user_id,
        )
        if not row:
            raise ValueError("coach profile not found")
        if not row["consent_public"]:
            raise ValueError("consent_public required")
        slug = validate_slug(row["public_slug"] or "")
        if not (row["seo_bio_md"] or "").strip():
            raise ValueError("seo_bio_md required")

        tags = row["specialty_tags"]
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = []

        content = await conn.fetchrow(
            """
            INSERT INTO marketing_content (
                content_type, platform, audience, title, draft_body, slug,
                status, created_by, published_at, public_path
            ) VALUES (
                'directory_page', 'public_site', 'providers', $1, $2, $3,
                'published', $4, NOW(), $5
            )
            RETURNING id
            """,
            row["display_name"] or slug,
            row["seo_bio_md"],
            slug,
            actor,
            f"/providers/{slug}.html",
        )
        content_id = int(content["id"])
        await conn.execute(
            """
            UPDATE coach_profiles
            SET directory_published = true,
                directory_content_id = $2,
                updated_at = NOW()
            WHERE coach_user_id = $1
            """,
            coach_user_id,
            content_id,
        )

    written = write_provider_page(
        display_name=row["display_name"] or slug,
        seo_bio_md=row["seo_bio_md"] or "",
        slug=slug,
        specialty_tags=list(tags or []),
        city=row.get("directory_city"),
    )
    regenerate_directory_sitemap()
    return {
        "ok": True,
        "coach_user_id": coach_user_id,
        "slug": slug,
        "content_id": content_id,
        **written,
    }


async def withdraw(db_pool, coach_user_id: str) -> Dict[str, Any]:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT public_slug FROM coach_profiles WHERE coach_user_id = $1",
            coach_user_id,
        )
        if not row or not row["public_slug"]:
            raise ValueError("no public_slug")
        slug = validate_slug(row["public_slug"])
        await conn.execute(
            """
            UPDATE coach_profiles
            SET directory_published = false, updated_at = NOW()
            WHERE coach_user_id = $1
            """,
            coach_user_id,
        )
    result = withdraw_provider_page(slug)
    regenerate_directory_sitemap()
    return result


async def rebuild_aggregation_pages(db_pool) -> Dict[str, Any]:
    """Publish city/specialty aggregation pages when min_profiles met."""
    async with db_pool.acquire() as conn:
        cfg = await conn.fetchval(
            "SELECT value FROM growth_config WHERE key = 'directory_min_profiles'"
        )
        mins = cfg if isinstance(cfg, dict) else {"city": 3, "specialty": 3}
        min_city = int(mins.get("city") or 3)
        min_spec = int(mins.get("specialty") or 3)
        city_rows = await conn.fetch(
            """
            SELECT directory_city AS key, array_agg(public_slug) AS slugs
            FROM coach_profiles
            WHERE directory_published = true
              AND public_slug IS NOT NULL
              AND directory_city IS NOT NULL AND directory_city <> ''
            GROUP BY directory_city
            HAVING COUNT(*) >= $1
            """,
            min_city,
        )
        # specialty from first specialty_tags element when present
        published = 0
        for r in city_rows:
            key = (r["key"] or "").strip()
            if not key:
                continue
            slug = re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")[:80]
            slugs = list(r["slugs"] or [])
            title = f"Coaches in {key}"
            html_body = (
                f"<h1>{html.escape(title)}</h1><ul>"
                + "".join(
                    f'<li><a href="/providers/{html.escape(s)}.html">{html.escape(s)}</a></li>'
                    for s in slugs
                )
                + "</ul>"
            )
            page_path = PUBLIC_SITE_ROOT / "providers" / f"city-{slug}.html"
            page_path.parent.mkdir(parents=True, exist_ok=True)
            page_path.write_text(
                f"<!DOCTYPE html><html><head><meta charset='utf-8'/><title>{html.escape(title)}</title>"
                f"<meta name='robots' content='index,follow'/></head><body>{html_body}</body></html>",
                encoding="utf-8",
            )
            await conn.execute(
                """
                INSERT INTO directory_pages (page_kind, slug, title, min_profiles, profile_slugs, published, html_path)
                VALUES ('city', $1, $2, $3, $4::jsonb, true, $5)
                ON CONFLICT (slug) DO UPDATE SET
                    profile_slugs = EXCLUDED.profile_slugs,
                    published = true,
                    html_path = EXCLUDED.html_path,
                    updated_at = NOW()
                """,
                f"city-{slug}",
                title,
                min_city,
                json.dumps(slugs),
                f"/providers/city-{slug}.html",
            )
            published += 1
            _try_deploy_copy(page_path)
        _ = min_spec  # specialty aggregation reserved (tags unpack) — city first
    regenerate_directory_sitemap()
    return {"ok": True, "pages_published": published}

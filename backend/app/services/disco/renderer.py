"""Worker #1 disco_canonical_renderer — one record → HTML + JSON-LD + llms."""

from __future__ import annotations

import json
from typing import Any

from app.services.disco.assets import llms_txt
from app.services.disco.pipeline import LocaleRouter, register_lint
from app.services.disco.workers_61_64 import InlineValueRenderer


def _esc(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def person_jsonld(record: dict[str, Any]) -> dict:
    phrases = record.get("canonical_phrases") or []
    same_as = record.get("same_as") or []
    if isinstance(same_as, str):
        try:
            parsed = json.loads(same_as)
            same_as = parsed if isinstance(parsed, list) else [same_as]
        except Exception:
            same_as = [same_as] if same_as else []
    same_as = [u for u in same_as if isinstance(u, str) and u.startswith("http")]
    return {
        "@context": "https://schema.org",
        "@type": "Person",
        "name": record.get("display_name"),
        "jobTitle": record.get("credential_string") or "Coach",
        "url": LocaleRouter.url("en", record.get("slug") or ""),
        "knowsAbout": phrases,
        "sameAs": same_as,
    }


def render_profile_html(
    record: dict[str, Any],
    *,
    relationship_class: str = "coaching",
    region: str = "US",
    value_unit: str = "grounding_60s",
) -> dict:
    """Zero-JS page. Crisis + value unit precede article (DAC45/46)."""
    body = record.get("bio") or record.get("profile_copy") or ""
    lint = register_lint(body + " " + (record.get("credential_string") or ""), relationship_class)
    if lint["blocked"]:
        return {"blocked": True, "lint": lint, "html": "", "jsonld": None}
    slug = record.get("slug") or "coach"
    name = _esc(record.get("display_name") or "Coach")
    cred = _esc(record.get("credential_string") or "")
    phrases = record.get("canonical_phrases") or []
    faq = record.get("faq") or []
    faq_html = "".join(
        f"<details><summary>{_esc(q.get('q', ''))}</summary><p>{_esc(q.get('a', ''))}</p></details>"
        for q in faq
        if isinstance(q, dict)
    )
    article = (
        f"<p class='crumb'><a href='/'>Sovereign Sanctuary</a> · "
        f"<a href='/coaches/{_esc(slug)}'>/coaches/{_esc(slug)}</a></p>"
        f"<h1>{name}</h1><p class='cred'>{cred}</p>"
        f"<p>{_esc(body)}</p>"
        f"<p class='phrases'>{_esc(', '.join(phrases))}</p>"
        f"{faq_html}"
        f"<p><a href='https://app.sovereignsanctuary.net/signup.html'>Sign up</a></p>"
    )
    value = InlineValueRenderer().render_page(article, value_unit, region)
    hreflang = LocaleRouter.hreflang_block(slug, record.get("languages") or ["en"])
    link_tags = "".join(
        f'<link rel="{t["rel"]}" hreflang="{t["hreflang"]}" href="{t["href"]}">' for t in hreflang
    )
    jsonld = person_jsonld({**record, "slug": slug})
    html = (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>{name} — Sovereign Sanctuary</title>"
        f"{link_tags}"
        f"<script type='application/ld+json'>{json.dumps(jsonld)}</script>"
        "</head><body>"
        f"{value}"
        "</body></html>"
    )
    # JSON-LD uses <script type=application/ld+json> — required by schema.
    # InlineValueRenderer forbids application JS; type=application/ld+json is markup.
    return {"blocked": False, "lint": lint, "html": html, "jsonld": jsonld}


def render_llms(directory_lines: list[str], *, agent_live: bool) -> str:
    extra = ""
    if directory_lines:
        extra = "\n## Listed coaches\n" + "\n".join(f"- {line}" for line in directory_lines) + "\n"
    return llms_txt(agent_endpoints_live=agent_live) + extra

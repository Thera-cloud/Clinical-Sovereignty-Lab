"""Staged Dispatch pipeline: topic → research → draft → critique.

# QUANTUM-CRYSTAL-ARCH — Little Nate Dispatch
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import aiohttp

logger = logging.getLogger("nate.newsletter_pipeline")

_YEAR_RE = re.compile(r"\b(202[4-9]|20[3-9]\d)\b")

ISSUE_SECTIONS = (
    "opener",
    "feature",
    "techniques",
    "go_deeper",
    "external_reading",
    "share",
    "ctas",
    "feedback",
    "safety_footer",
)

SAFETY_FOOTER = (
    "Little Nate is an AI companion for education and support — not a therapist "
    "and not medical advice. If you are in crisis, call or text 988 (US) or visit "
    "https://findahelpline.com. Unsubscribe anytime via the link below."
)


async def _load_symbolic_hints(db_pool) -> List[str]:
    """Marketing symbolic memory only — never inject into therapy prompts."""
    if not db_pool:
        return []
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT content FROM newsletter_symbolic_memory
                WHERE scope = 'active' AND kind IN ('rule', 'style_note', 'outcome')
                  AND confidence >= 0.55
                ORDER BY confidence DESC, created_at DESC
                LIMIT 5
                """
            )
        return [r["content"][:300] for r in rows if r.get("content")]
    except Exception as e:
        logger.warning("symbolic hints: %s", e)
        return []


async def select_topic(db_pool) -> Dict[str, Any]:
    """Score topics from signals, forecast, seasonal calendar, symbolic rules."""
    topic = {
        "topic_key": "anxiety_reach_out",
        "title": "When anxiety asks you to shrink — reaching out anyway",
        "seasonal_window": None,
        "rationale": "default_bootstrap",
        "symbolic_hints": [],
    }
    if not db_pool:
        return topic
    try:
        hints = await _load_symbolic_hints(db_pool)
        topic["symbolic_hints"] = hints
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT theme, count_bucket FROM newsletter_chat_signals
                WHERE count_bucket >= 3
                ORDER BY count_bucket DESC, week_bucket DESC
                LIMIT 1
                """
            )
            if row:
                theme = row["theme"]
                topic = {
                    "topic_key": re.sub(r"[^a-z0-9_]+", "_", theme.lower())[:64],
                    "title": theme[:120],
                    "seasonal_window": None,
                    "rationale": f"chat_signal_n={row['count_bucket']}",
                    "symbolic_hints": hints,
                }
            else:
                forecast = await conn.fetchrow(
                    """
                    SELECT topic_key, seasonal_label, foresight_score
                    FROM newsletter_topic_forecast
                    WHERE target_week >= CURRENT_DATE - INTERVAL '14 days'
                    ORDER BY foresight_score DESC, created_at DESC
                    LIMIT 1
                    """
                )
                if forecast and forecast["topic_key"]:
                    key = forecast["topic_key"]
                    topic = {
                        "topic_key": key[:64],
                        "title": key.replace("_", " ")[:120],
                        "seasonal_window": forecast.get("seasonal_label"),
                        "rationale": f"forecast_score={forecast['foresight_score']}",
                        "symbolic_hints": hints,
                    }
            recent = await conn.fetchval(
                """
                SELECT topic FROM newsletter_issues
                WHERE status = 'sent' AND topic IS NOT NULL
                ORDER BY sent_at DESC NULLS LAST LIMIT 1
                """
            )
            if recent and recent == topic.get("title"):
                topic["title"] = "Building steadiness through small daily check-ins"
                topic["topic_key"] = "daily_steadiness"
                topic["rationale"] = "anti_repeat"
    except Exception as e:
        logger.warning("select_topic fallback: %s", e)
    return topic


async def verify_url(url: str, session: aiohttp.ClientSession) -> Tuple[int, bool]:
    try:
        async with session.head(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=8)) as resp:
            code = resp.status
            if code >= 400:
                async with session.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=8)) as g:
                    code = g.status
            return code, 200 <= code < 400
    except Exception:
        return 0, False


async def build_research_bundle(topic: Dict[str, Any]) -> Dict[str, Any]:
    """Allowlisted 2024+ sources with URL liveness. Fail closed if none verify."""
    # Curated starter set — composer may only cite from verified bundle
    candidates = [
        {
            "source_name": "APA — Stress in America",
            "year": 2024,
            "url": "https://www.apa.org/news/press/releases/stress",
            "modality": "psychoeducation",
        },
        {
            "source_name": "NIMH — Anxiety Disorders",
            "year": 2024,
            "url": "https://www.nimh.nih.gov/health/topics/anxiety-disorders",
            "modality": "psychoeducation",
        },
        {
            "source_name": "SAMHSA — Find Help",
            "year": 2024,
            "url": "https://www.samhsa.gov/find-help",
            "modality": "help_seeking",
        },
        {
            "source_name": "WHO — Mental health",
            "year": 2024,
            "url": "https://www.who.int/health-topics/mental-health",
            "modality": "psychoeducation",
        },
    ]
    verified = []
    async with aiohttp.ClientSession() as session:
        for c in candidates:
            if int(c["year"]) < 2024:
                continue
            code, ok = await verify_url(c["url"], session)
            c = {**c, "http_status_checked": code, "verified": ok}
            if ok:
                verified.append(c)
    return {
        "topic": topic,
        "citations": verified,
        "external_reading": verified[0] if verified else None,
        "built_at": datetime.now(timezone.utc).isoformat(),
    }


def _slugify(title: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (title or "dispatch").lower()).strip("-")[:60]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"{stamp}-{base}"


def draft_issue_from_bundle(topic: Dict[str, Any], bundle: Dict[str, Any]) -> Dict[str, Any]:
    cites = bundle.get("citations") or []
    if not cites:
        raise ValueError("research_bundle has no verified citations — fail closed")

    cite_lines = []
    for c in cites[:5]:
        cite_lines.append(f"- {c['source_name']} ({c['year']}): {c['url']}")

    techniques = [
        {
            "step": 1,
            "text": "Name what you feel in one plain sentence (affect labeling).",
            "modality": "CBT",
        },
        {
            "step": 2,
            "text": "Ground for 60 seconds: feet, breath, one object in the room.",
            "modality": "somatic",
        },
        {
            "step": 3,
            "text": "Ask for one concrete kind of support from a safe person or Little Nate.",
            "modality": "MI",
        },
    ]

    hints = topic.get("symbolic_hints") or []
    hint_block = ""
    if hints:
        hint_block = "\n\n_Editor notes (from prior Dispatch outcomes):_\n" + "\n".join(
            f"- {h}" for h in hints[:3]
        )

    opener = (
        "You do not have to earn rest or connection. Strength includes asking — "
        "and I am here when you are ready to take the next small step."
    )
    feature = (
        f"## {topic.get('title')}\n\n"
        "This week we explore how overwhelm can make reaching out feel risky — "
        "and how small, structured steps restore agency without forcing a perfect plan.\n\n"
        "Clinical context (education only, not diagnosis):\n"
        + "\n".join(cite_lines)
        + hint_block
    )
    go_deeper = (
        "Try opening with Little Nate:\n"
        "1. \"I keep putting off asking for help — sit with me in that.\"\n"
        "2. \"What am I protecting by staying quiet?\"\n"
        "3. \"Help me practice one sentence I could send to someone safe.\""
    )
    external = bundle.get("external_reading") or cites[0]
    body = "\n\n".join(
        [
            opener,
            feature,
            "## Techniques\n"
            + "\n".join(
                f"{t['step']}. {t['text']} _(modality: {t['modality']})_" for t in techniques
            ),
            "## Go Deeper with Little Nate\n" + go_deeper,
            f"## Further reading\n[{external['source_name']}]({external['url']})",
            "## Share\nForward this issue or use the share links in your email.",
            "## Next steps\nJoin Sovereign Sanctuary or try 20 free questions with Nate.",
            SAFETY_FOOTER,
        ]
    )
    slug = _slugify(topic.get("title") or topic.get("topic_key") or "dispatch")
    return {
        "slug": slug,
        "topic": topic.get("title"),
        "subject_line": f"Little Nate Dispatch: {topic.get('title')}",
        "opener": opener,
        "body_md": body,
        "draft_body": body,
        "techniques": techniques,
        "citations": cites,
        "external_link": external["url"],
        "research_bundle": bundle,
        "content_hash": hashlib.sha256(body.encode()).hexdigest(),
    }


async def draft_issue_llm(topic: Dict[str, Any], bundle: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Optional inference-router compose; cites must stay within research_bundle."""
    import os

    if os.getenv("ENABLE_NEWSLETTER_LLM_DRAFT", "false").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return None
    cites = bundle.get("citations") or []
    if not cites:
        return None
    cite_blob = "\n".join(
        f"- {c['source_name']} ({c['year']}): {c['url']}" for c in cites[:5]
    )
    hints = "\n".join(topic.get("symbolic_hints") or [])
    system = (
        "You write Little Nate Dispatch — warm, educational mental-health newsletter. "
        "NOT therapy or diagnosis. Cite ONLY URLs from the research list. "
        "Include crisis footer with 988 and findahelpline.com. "
        "Output markdown with sections: opener, feature, techniques (3), go deeper, further reading."
    )
    user = (
        f"Topic: {topic.get('title')}\n\nAllowed citations:\n{cite_blob}\n\n"
        f"Style hints:\n{hints or '(none)'}\n\n"
        f"Must end with: {SAFETY_FOOTER}"
    )
    try:
        from app.services.nate_inference_router import NateInferenceRouter

        router = NateInferenceRouter()
        result = await router.generate(
            prompt=user,
            system=system,
            domain="marketing",
            max_tokens=1200,
        )
        text = ""
        if isinstance(result, dict):
            text = (result.get("text") or result.get("content") or "").strip()
        elif isinstance(result, str):
            text = result.strip()
        if len(text) < 200:
            return None
        base = draft_issue_from_bundle(topic, bundle)
        base["body_md"] = text
        base["draft_body"] = text
        base["opener"] = text.split("\n", 1)[0][:400]
        base["content_hash"] = hashlib.sha256(text.encode()).hexdigest()
        base["research_bundle"] = {**bundle, "llm_draft": True}
        return base
    except Exception as e:
        logger.warning("LLM draft failed, using template: %s", e)
        return None


def critique_issue(draft: Dict[str, Any], bundle: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Fail closed on citation mismatch, missing footer, year < 2024."""
    errors: List[str] = []
    body = draft.get("body_md") or ""
    if "988" not in body and "findahelpline" not in body.lower():
        errors.append("missing_crisis_footer")
    if "not a therapist" not in body.lower() and "not medical advice" not in body.lower():
        errors.append("missing_disclaimer")

    allowed = {c["url"] for c in (bundle.get("citations") or []) if c.get("verified")}
    draft_urls = set(re.findall(r"https?://[^\s\)\]]+", body))
    for u in draft_urls:
        # Allow sanctuary / library / crisis links outside clinical cites
        host = urlparse(u).netloc.lower()
        if any(
            h in host
            for h in (
                "sovereignsanctuary.net",
                "findahelpline.com",
                "988lifeline.org",
                "samhsa.gov",
            )
        ):
            continue
        if u.rstrip(").,") not in allowed and not any(u.startswith(a) for a in allowed):
            # soft: only flag if looks like citation domain
            if any(k in host for k in ("apa.org", "nimh.nih.gov", "who.int", "nih.gov")):
                if u.rstrip(").,") not in allowed:
                    errors.append(f"ungrounded_cite:{u[:80]}")

    for c in draft.get("citations") or []:
        if int(c.get("year") or 0) < 2024:
            errors.append(f"year_too_old:{c.get('url')}")
        if c.get("url") not in allowed and not c.get("verified"):
            errors.append(f"unverified_cite:{c.get('url')}")

    techniques = draft.get("techniques") or []
    if not (1 <= len(techniques) <= 5):
        errors.append("techniques_count")

    return len(errors) == 0, errors


async def persist_issue(db_pool, draft: Dict[str, Any], status: str = "in_review") -> Optional[str]:
    if not db_pool:
        return None
    async with db_pool.acquire() as conn:
        issue_id = await conn.fetchval(
            """
            INSERT INTO newsletter_issues (
                slug, status, topic, subject_line, opener, body_md, draft_body,
                techniques, citations, external_link, research_bundle, content_hash
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7,
                $8::jsonb, $9::jsonb, $10, $11::jsonb, $12
            )
            ON CONFLICT (slug) DO UPDATE SET
                status = EXCLUDED.status,
                topic = EXCLUDED.topic,
                subject_line = EXCLUDED.subject_line,
                opener = EXCLUDED.opener,
                body_md = EXCLUDED.body_md,
                draft_body = EXCLUDED.draft_body,
                techniques = EXCLUDED.techniques,
                citations = EXCLUDED.citations,
                external_link = EXCLUDED.external_link,
                research_bundle = EXCLUDED.research_bundle,
                content_hash = EXCLUDED.content_hash,
                updated_at = NOW()
            RETURNING id
            """,
            draft["slug"],
            status,
            draft.get("topic"),
            draft.get("subject_line"),
            draft.get("opener"),
            draft.get("body_md"),
            draft.get("draft_body"),
            json.dumps(draft.get("techniques") or []),
            json.dumps(draft.get("citations") or []),
            draft.get("external_link"),
            json.dumps(draft.get("research_bundle") or {}),
            draft.get("content_hash"),
        )
        for c in draft.get("citations") or []:
            await conn.execute(
                """
                INSERT INTO newsletter_citations
                    (issue_id, source_name, year, url, modality, http_status_checked, verified_at)
                VALUES ($1, $2, $3, $4, $5, $6, NOW())
                """,
                issue_id,
                c.get("source_name"),
                int(c.get("year") or 2024),
                c.get("url"),
                c.get("modality"),
                c.get("http_status_checked"),
            )
        return str(issue_id)

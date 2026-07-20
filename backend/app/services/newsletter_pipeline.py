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

VETERANS_CRISIS_LINE = (
    " Veterans and service members: Veterans Crisis Line — dial 988 then press 1, "
    "or text 838255 (US)."
)

# Domain-tagged citation allowlist (2024+). Composer may only cite verified bundle.
CITATION_ALLOWLIST = [
    {
        "source_name": "APA — Stress in America",
        "year": 2024,
        "url": "https://www.apa.org/news/press/releases/stress",
        "modality": "psychoeducation",
        "domains": ("general", "burnout", "curiosity"),
    },
    {
        "source_name": "NIMH — Anxiety Disorders",
        "year": 2024,
        "url": "https://www.nimh.nih.gov/health/topics/anxiety-disorders",
        "modality": "psychoeducation",
        "domains": ("general", "relationships", "parenting"),
    },
    {
        "source_name": "SAMHSA — Find Help",
        "year": 2024,
        "url": "https://www.samhsa.gov/find-help",
        "modality": "help_seeking",
        "domains": ("general", "grief", "burnout"),
    },
    {
        "source_name": "WHO — Mental health",
        "year": 2024,
        "url": "https://www.who.int/health-topics/mental-health",
        "modality": "psychoeducation",
        "domains": ("general", "curiosity"),
    },
    {
        "source_name": "CDC — Autism Spectrum Disorder",
        "year": 2024,
        "url": "https://www.cdc.gov/autism/index.html",
        "modality": "psychoeducation",
        "domains": ("neurodivergence",),
    },
    {
        "source_name": "NIMH — ADHD",
        "year": 2024,
        "url": "https://www.nimh.nih.gov/health/topics/attention-deficit-hyperactivity-disorder-adhd",
        "modality": "psychoeducation",
        "domains": ("neurodivergence",),
    },
    {
        "source_name": "CHADD — ADHD",
        "year": 2024,
        "url": "https://chadd.org/",
        "modality": "advocacy",
        "domains": ("neurodivergence",),
    },
    {
        "source_name": "National Center for PTSD (VA)",
        "year": 2024,
        "url": "https://www.ptsd.va.gov/",
        "modality": "psychoeducation",
        "domains": ("military", "grief"),
    },
    {
        "source_name": "VA — Mental Health",
        "year": 2024,
        "url": "https://www.mentalhealth.va.gov/",
        "modality": "help_seeking",
        "domains": ("military",),
    },
    {
        "source_name": "NEA — Arts and Health",
        "year": 2024,
        "url": "https://www.arts.gov/impact/arts-health",
        "modality": "psychoeducation",
        "domains": ("arts", "curiosity", "fitness"),
    },
    {
        "source_name": "NIH — Physical Activity and Mental Health",
        "year": 2024,
        "url": "https://www.nimh.nih.gov/health/topics/caring-for-your-mental-health",
        "modality": "psychoeducation",
        "domains": ("fitness", "sleep", "general"),
    },
]


def safety_footer_for_domain(domain: Optional[str] = None) -> str:
    footer = SAFETY_FOOTER
    if (domain or "").lower() in ("military", "veteran", "war"):
        footer = footer.replace(
            "Unsubscribe anytime via the link below.",
            VETERANS_CRISIS_LINE + " Unsubscribe anytime via the link below.",
        )
    return footer


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
    """Score topics from the growth engine pool (signals, forecast, trends, seasons)."""
    try:
        from app.services.newsletter_topic_engine import select_best_topic

        return await select_best_topic(db_pool)
    except Exception as e:
        logger.warning("select_topic growth engine fallback: %s", e)
        hints = await _load_symbolic_hints(db_pool)
        return {
            "topic_key": "curiosity_lifelong_learning",
            "title": "Staying curious when the world feels loud",
            "seasonal_window": None,
            "domain": "curiosity",
            "rationale": "default_bootstrap",
            "symbolic_hints": hints,
        }


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
    """Allowlisted 2024+ sources with URL liveness. Domain-aware; fail closed if none verify."""
    try:
        from app.services.newsletter_topic_engine import infer_domain
    except Exception:
        infer_domain = lambda t: "general"  # noqa: E731

    domain = (topic.get("domain") or infer_domain(
        f"{topic.get('title') or ''} {topic.get('topic_key') or ''}"
    )).lower()

    # Prefer domain-matched sources, then general, then any remaining
    domain_first = [
        c for c in CITATION_ALLOWLIST if domain in c.get("domains", ())
    ]
    general = [
        c for c in CITATION_ALLOWLIST
        if "general" in c.get("domains", ()) and c not in domain_first
    ]
    rest = [c for c in CITATION_ALLOWLIST if c not in domain_first and c not in general]
    ordered = (domain_first + general + rest)[:8]

    verified = []
    async with aiohttp.ClientSession() as session:
        for c in ordered:
            if int(c["year"]) < 2024:
                continue
            code, ok = await verify_url(c["url"], session)
            row = {
                "source_name": c["source_name"],
                "year": c["year"],
                "url": c["url"],
                "modality": c["modality"],
                "http_status_checked": code,
                "verified": ok,
            }
            if ok:
                verified.append(row)
            if len(verified) >= 5:
                break
    return {
        "topic": topic,
        "domain": domain,
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
    # Symbolic memory may shape tone; never dump raw editor instructions into the body.
    rewrite = (bundle.get("editor_rewrite_notes") or "").strip()
    rewrite = re.sub(r"\s+", " ", rewrite)[:400]

    opener = (
        "You do not have to earn rest or connection. Strength includes asking — "
        "and I am here when you are ready to take the next small step."
    )
    if rewrite:
        feature_lead = (
            f"This week we explore {topic.get('title') or 'steadiness'} with a sharper focus "
            f"on what your editor asked for: {rewrite}. "
            "Small, structured steps restore agency without forcing a perfect plan.\n\n"
        )
    else:
        feature_lead = (
            "This week we explore how overwhelm can make reaching out feel risky — "
            "and how small, structured steps restore agency without forcing a perfect plan.\n\n"
        )
    feature = (
        f"## {topic.get('title')}\n\n"
        + feature_lead
        + "Clinical context (education only, not diagnosis):\n"
        + "\n".join(cite_lines)
    )
    if hints and not rewrite:
        feature += "\n\n_Voice notes (from prior Dispatch outcomes):_\n" + "\n".join(
            f"- {h}" for h in hints[:3]
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
            safety_footer_for_domain(topic.get("domain") or bundle.get("domain")),
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


async def draft_issue_llm(
    topic: Dict[str, Any],
    bundle: Dict[str, Any],
    *,
    force: bool = False,
) -> Optional[Dict[str, Any]]:
    """Optional inference-router compose; cites must stay within research_bundle.

    force=True bypasses ENABLE_NEWSLETTER_LLM_DRAFT (editor rewrite path).
    """
    import os

    if not force and os.getenv("ENABLE_NEWSLETTER_LLM_DRAFT", "false").strip().lower() not in (
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
    rewrite = (bundle.get("editor_rewrite_notes") or "").strip()
    system = (
        "You write Little Nate Dispatch — warm, educational mental-health newsletter. "
        "NOT therapy or diagnosis. Cite ONLY URLs from the research list. "
        "Include crisis footer with 988 and findahelpline.com. "
        "Never paste editor instructions verbatim into the article. "
        "Output markdown with sections: opener, feature, techniques (3), go deeper, further reading."
    )
    user = (
        f"Topic: {topic.get('title')}\n\nAllowed citations:\n{cite_blob}\n\n"
        f"Style hints:\n{hints or '(none)'}\n\n"
        + (f"EDITOR REWRITE DIRECTION (apply, do not quote):\n{rewrite}\n\n" if rewrite else "")
        + f"Must end with: {safety_footer_for_domain(topic.get('domain') or bundle.get('domain'))}"
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


async def rewrite_existing_issue(
    db_pool, issue_id: str, notes: str = ""
) -> Dict[str, Any]:
    """Regenerate body for an in-review/draft/rejected issue; keep slug."""
    if not db_pool:
        return {"ok": False, "error": "no_db"}
    notes = (notes or "").strip()[:2000]
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM newsletter_issues WHERE id = $1::uuid", issue_id
        )
    if not row:
        return {"ok": False, "error": "not_found"}
    if row["status"] not in ("in_review", "draft", "rejected"):
        return {"ok": False, "error": "wrong_status", "status": row["status"]}

    bundle = row["research_bundle"] or {}
    if isinstance(bundle, str):
        try:
            bundle = json.loads(bundle)
        except Exception:
            bundle = {}
    if not isinstance(bundle, dict):
        bundle = {}
    cites = bundle.get("citations") or []
    if isinstance(row["citations"], list) and row["citations"]:
        cites = cites or row["citations"]
    if isinstance(cites, str):
        try:
            cites = json.loads(cites)
        except Exception:
            cites = []
    bundle = {**bundle, "citations": cites}
    if notes:
        bundle["editor_rewrite_notes"] = notes
        hist = list(bundle.get("rewrite_history") or [])
        hist.append(
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "notes": notes[:500],
            }
        )
        bundle["rewrite_history"] = hist[-10:]

    if not cites:
        return {"ok": False, "error": "no_citations_on_issue"}

    topic = {
        "title": row["topic"] or row["slug"],
        "topic_key": row["slug"],
        "symbolic_hints": [],
    }
    draft = await draft_issue_llm(topic, bundle, force=bool(notes))
    if not draft:
        draft = draft_issue_from_bundle(topic, bundle)
    draft["slug"] = row["slug"]
    draft["topic"] = row["topic"] or draft.get("topic")
    ok, errors = critique_issue(draft, bundle)
    if not ok:
        return {"ok": False, "errors": errors}

    # Refresh image descriptor from topic; clear stale hero so preview/send regenerate
    try:
        from app.services.newsletter_imagery import build_hero_prompt

        new_prompt = build_hero_prompt(
            draft.get("topic") or row["topic"] or "",
            draft.get("subject_line") or row["subject_line"] or "",
        )
    except Exception:
        new_prompt = None

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE newsletter_issues SET
                status = 'in_review',
                subject_line = $2,
                opener = $3,
                body_md = $4,
                draft_body = $5,
                final_body = NULL,
                techniques = $6::jsonb,
                citations = $7::jsonb,
                research_bundle = $8::jsonb,
                content_hash = $9,
                rejected_reason = NULL,
                hero_image_prompt = COALESCE($10, hero_image_prompt),
                hero_image_url = NULL,
                hero_image_r2_key = NULL,
                hero_image_generated_at = NULL,
                updated_at = NOW()
            WHERE id = $1::uuid
            """,
            issue_id,
            draft.get("subject_line"),
            draft.get("opener"),
            draft.get("body_md"),
            draft.get("draft_body") or draft.get("body_md"),
            json.dumps(draft.get("techniques") or []),
            json.dumps(draft.get("citations") or cites),
            json.dumps(bundle),
            draft.get("content_hash"),
            new_prompt,
        )
    return {
        "ok": True,
        "issue_id": issue_id,
        "slug": row["slug"],
        "hero_reset": True,
    }


async def find_open_issue_this_week(db_pool) -> Optional[Dict[str, Any]]:
    """Return newest non-sent pipeline issue created this UTC week (if any)."""
    if not db_pool:
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, slug, status, topic, content_hash, created_at
                FROM newsletter_issues
                WHERE status IN (
                    'draft', 'researching', 'composing', 'critiquing',
                    'in_review', 'approved'
                )
                  AND created_at >= date_trunc('week', NOW() AT TIME ZONE 'UTC')
                ORDER BY created_at DESC
                LIMIT 1
                """
            )
        return dict(row) if row else None
    except Exception as e:
        logger.warning("find_open_issue_this_week: %s", e)
        return None


async def reject_replicate_open_issues(db_pool) -> Dict[str, Any]:
    """Keep newest open draft per content_hash / topic+day; reject older replicates."""
    if not db_pool:
        return {"rejected": 0}
    rejected = 0
    async with db_pool.acquire() as conn:
        # Same content_hash among open issues
        rows = await conn.fetch(
            """
            SELECT id, content_hash, created_at
            FROM newsletter_issues
            WHERE status IN ('draft', 'in_review', 'approved', 'rejected')
              AND content_hash IS NOT NULL
              AND content_hash <> ''
              AND created_at > NOW() - INTERVAL '30 days'
            ORDER BY content_hash, created_at DESC
            """
        )
        seen_hash = set()
        for r in rows:
            ch = r["content_hash"]
            if ch in seen_hash:
                if r["id"]:
                    # only reject draft/in_review/approved (not already rejected)
                    did = await conn.fetchval(
                        """
                        UPDATE newsletter_issues
                        SET status = 'rejected',
                            rejected_reason = 'replicate_content_hash',
                            updated_at = NOW()
                        WHERE id = $1
                          AND status IN ('draft', 'in_review', 'approved')
                        RETURNING id
                        """,
                        r["id"],
                    )
                    if did:
                        rejected += 1
            else:
                seen_hash.add(ch)
        # Same topic same UTC day among open issues
        topic_rows = await conn.fetch(
            """
            SELECT id, topic, (created_at AT TIME ZONE 'UTC')::date AS d, created_at
            FROM newsletter_issues
            WHERE status IN ('draft', 'in_review', 'approved')
              AND topic IS NOT NULL AND topic <> ''
              AND created_at > NOW() - INTERVAL '14 days'
            ORDER BY topic, d, created_at DESC
            """
        )
        seen_topic_day = set()
        for r in topic_rows:
            key = (str(r["topic"]).strip().lower(), str(r["d"]))
            if key in seen_topic_day:
                did = await conn.fetchval(
                    """
                    UPDATE newsletter_issues
                    SET status = 'rejected',
                        rejected_reason = 'replicate_topic_same_day',
                        updated_at = NOW()
                    WHERE id = $1 AND status IN ('draft', 'in_review', 'approved')
                    RETURNING id
                    """,
                    r["id"],
                )
                if did:
                    rejected += 1
            else:
                seen_topic_day.add(key)
    return {"rejected": rejected}


async def persist_issue(db_pool, draft: Dict[str, Any], status: str = "in_review") -> Optional[str]:
    if not db_pool:
        return None
    import secrets as _secrets

    slug = draft.get("slug") or _slugify(draft.get("topic") or "dispatch")
    ch = draft.get("content_hash")

    async with db_pool.acquire() as conn:
        # Never create a second open issue that clones recently sent content
        if ch:
            twin = await conn.fetchval(
                """
                SELECT slug FROM newsletter_issues
                WHERE content_hash = $1 AND status = 'sent'
                  AND sent_at > NOW() - INTERVAL '180 days'
                LIMIT 1
                """,
                ch,
            )
            if twin:
                logger.warning("persist_issue blocked duplicate of sent slug=%s", twin)
                return None

        issue_id = None
        for _attempt in range(6):
            existing = await conn.fetchrow(
                "SELECT id, status FROM newsletter_issues WHERE slug = $1", slug
            )
            if existing and existing["status"] in ("sent", "approved"):
                # Never overwrite sent/approved — mint a unique slug
                slug = f"{draft.get('slug') or _slugify('dispatch')}-{_secrets.token_hex(2)}"
                draft["slug"] = slug
                continue
            if existing and existing["status"] in (
                "draft",
                "in_review",
                "rejected",
                "researching",
                "composing",
                "critiquing",
            ):
                issue_id = await conn.fetchval(
                    """
                    UPDATE newsletter_issues SET
                        status = $2,
                        topic = $3,
                        subject_line = $4,
                        opener = $5,
                        body_md = $6,
                        draft_body = $7,
                        techniques = $8::jsonb,
                        citations = $9::jsonb,
                        external_link = $10,
                        research_bundle = $11::jsonb,
                        content_hash = $12,
                        updated_at = NOW()
                    WHERE id = $1
                      AND status IN (
                        'draft', 'in_review', 'rejected',
                        'researching', 'composing', 'critiquing'
                      )
                    RETURNING id
                    """,
                    existing["id"],
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
                    ch,
                )
                if issue_id:
                    break
                slug = f"{slug}-{_secrets.token_hex(2)}"
                draft["slug"] = slug
                continue
            issue_id = await conn.fetchval(
                """
                INSERT INTO newsletter_issues (
                    slug, status, topic, subject_line, opener, body_md, draft_body,
                    techniques, citations, external_link, research_bundle, content_hash
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7,
                    $8::jsonb, $9::jsonb, $10, $11::jsonb, $12
                )
                RETURNING id
                """,
                slug,
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
                ch,
            )
            draft["slug"] = slug
            break

        if not issue_id:
            return None
        await conn.execute(
            "DELETE FROM newsletter_citations WHERE issue_id = $1", issue_id
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

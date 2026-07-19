"""Dedicated Story Library crystal recall (metadata.origin filter).

# QUANTUM-CRYSTAL-ARCH — Little Nate Dispatch
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger("nate.newsletter_library_recall")


async def recall_newsletter_library_context(
    db_pool,
    query_text: str,
    *,
    max_issues: int = 3,
    surface: str = "bridge_chat",
    trial_safe_only: bool = False,
) -> str:
    """Return labeled Library block or empty string."""
    if not db_pool:
        return ""
    from app.services.recall_exfil_guard import guard_recall

    blocked = await guard_recall(db_pool, query_text, surface)
    if blocked is not None:
        return ""

    q = (query_text or "").strip()
    rows = await _fetch_library_crystals(
        db_pool, q, max_issues=max_issues, trial_safe_only=trial_safe_only
    )
    if not rows:
        return ""

    try:
        from app.services.nate_response_validator import NateResponseValidator

        rows = NateResponseValidator.filter_recalled_crystals(rows) or rows
    except Exception:
        pass

    if not rows:
        return ""

    lines = [
        "FROM LITTLE NATE'S STORY LIBRARY (editorial, not personal memory):",
        "When citing, use the exact issue title below. Never invent a Dispatch issue.",
    ]
    for r in rows[:max_issues]:
        meta = r.get("metadata") or {}
        if isinstance(meta, str):
            import json

            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        title = meta.get("title") or meta.get("slug") or "Dispatch issue"
        slug = meta.get("slug") or ""
        text = (r.get("crystal_text") or r.get("text") or "")[:600]
        lines.append(f"- [{title}] slug={slug}: {text}")
    return "\n".join(lines)


async def _fetch_library_crystals(
    db_pool,
    query_text: str,
    *,
    max_issues: int,
    trial_safe_only: bool,
) -> List[Dict[str, Any]]:
    has_q = len(query_text) >= 8
    try:
        async with db_pool.acquire() as conn:
            if has_q:
                rows = await conn.fetch(
                    """
                    SELECT id, crystal_text, confidence, domain, metadata
                    FROM nate_intelligence_crystals
                    WHERE user_id IS NULL
                      AND scope = 'global'
                      AND superseded_by IS NULL
                      AND metadata->>'origin' = 'newsletter_library'
                      AND (
                        COALESCE(metadata->>'editorial_status', 'published') = 'published'
                      )
                      AND (
                        NOT $3::bool
                        OR COALESCE((metadata->>'trial_safe')::boolean, false) = true
                      )
                      AND (
                        crystal_text ILIKE '%' || $1 || '%'
                        OR COALESCE(metadata->>'title', '') ILIKE '%' || $1 || '%'
                        OR COALESCE(metadata->>'slug', '') ILIKE '%' || $1 || '%'
                      )
                    ORDER BY COALESCE((metadata->>'published_at')::timestamptz, created_at) DESC
                    LIMIT $2
                    """,
                    query_text[:200],
                    max_issues,
                    trial_safe_only,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT id, crystal_text, confidence, domain, metadata
                    FROM nate_intelligence_crystals
                    WHERE user_id IS NULL
                      AND scope = 'global'
                      AND superseded_by IS NULL
                      AND metadata->>'origin' = 'newsletter_library'
                      AND COALESCE(metadata->>'editorial_status', 'published') = 'published'
                      AND (
                        NOT $2::bool
                        OR COALESCE((metadata->>'trial_safe')::boolean, false) = true
                      )
                    ORDER BY COALESCE((metadata->>'published_at')::timestamptz, created_at) DESC
                    LIMIT $1
                    """,
                    max_issues,
                    trial_safe_only,
                )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("newsletter library recall failed: %s", e)
        return []


async def recall_trial_editorial_only(
    db_pool, query_text: str, *, max_issues: int = 2
) -> str:
    """Public 20Q path — published trial_safe Library crystals only."""
    import os

    if os.getenv("ENABLE_TRIAL_LIBRARY_EDITORIAL", "false").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return ""
    return await recall_newsletter_library_context(
        db_pool,
        query_text,
        max_issues=max_issues,
        surface="public_trial",
        trial_safe_only=True,
    )


async def crystallize_sent_issue(db_pool, issue: Dict[str, Any]) -> Optional[str]:
    """Store global editorial crystal for a sent issue."""
    if not db_pool or not issue:
        return None
    body = (issue.get("final_body") or issue.get("body_md") or "").strip()
    if len(body) < 80:
        return None
    title = issue.get("topic") or issue.get("subject_line") or issue.get("slug")
    slug = issue.get("slug")
    text = f"Little Nate Dispatch — {title}\n\n{body[:3500]}"
    try:
        from app.services.crystal_phi_guard import guard_global_crystal_write

        ok = await guard_global_crystal_write(
            db_pool, text, scope="global", context="newsletter_issue"
        )
        if not ok:
            logger.warning("PHI guard blocked newsletter crystal for slug=%s", slug)
            return None
    except Exception as e:
        logger.warning("PHI guard error on newsletter crystal: %s", e)
        return None
    try:
        from app.services.nate_response_validator import NateResponseValidator

        violations = await NateResponseValidator().validate(text)
        high = False
        for v in violations or []:
            sev = v.get("severity") if isinstance(v, dict) else getattr(v, "severity", "")
            if sev == "high":
                high = True
                break
        if high:
            logger.warning("Validator blocked newsletter crystal for slug=%s", slug)
            return None
    except Exception:
        pass

    import hashlib
    import json
    from datetime import datetime, timezone

    content_hash = hashlib.sha256(text.encode()).hexdigest()
    meta = {
        "origin": "newsletter_library",
        "slug": slug,
        "issue_id": str(issue.get("id") or ""),
        "title": title,
        "editorial_status": "published",
        "trial_safe": True,
        "published_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        async with db_pool.acquire() as conn:
            crystal_id = await conn.fetchval(
                """
                INSERT INTO nate_intelligence_crystals
                    (crystal_text, domain, scope, topics, source_count,
                     confidence, content_hash, metadata, user_id)
                VALUES ($1, 'research', 'global', $2::text[], 2, 0.70, $3, $4::jsonb, NULL)
                RETURNING id
                """,
                text,
                [slug or "dispatch", "newsletter_library"],
                content_hash,
                json.dumps(meta),
            )
            await conn.execute(
                "UPDATE newsletter_issues SET crystal_id = $1, updated_at = NOW() WHERE id = $2",
                crystal_id,
                issue["id"],
            )
            await conn.execute(
                """
                INSERT INTO newsletter_library_stats (slug, view_count, chat_reference_count)
                VALUES ($1, 0, 0)
                ON CONFLICT (slug) DO NOTHING
                """,
                slug,
            )
        # Vectorize index (outside DB connection) — QUANTUM-CRYSTAL-ARCH
        try:
            from app.services.vectorize_service import index_wisdom

            await index_wisdom(
                user_id="",
                wisdom_id=str(crystal_id),
                insight_type="newsletter_library",
                content=text[:2000],
                source="newsletter_library",
                domain="research",
            )
        except Exception as ve:
            logger.warning("newsletter vectorize index failed: %s", ve)
        return str(crystal_id)
    except Exception as e:
        logger.warning("crystallize_sent_issue failed: %s", e)
        return None

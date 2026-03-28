"""
Bridge-side crystal recall + crystallization pipeline.

Uses the bridge's existing db_pool (no HTTP calls to backend).
- recall: retrieves user-scoped + global crystals, logs recalls, reinforces
- crystallize: extracts new user-scoped crystals from conversations
"""
import hashlib
import logging
import re

logger = logging.getLogger(__name__)

_CRYSTAL_SIGNALS = [
    (re.compile(r"\b(i feel|i felt|feeling|i'm afraid|i'm scared)\b", re.I), "clinical", 2),
    (re.compile(r"\b(i need|i want|i long for|i wish)\b", re.I), "clinical", 2),
    (re.compile(r"\b(ashamed|shame|guilt|worthless|inadequate)\b", re.I), "clinical", 3),
    (re.compile(r"\b(angry|furious|frustrated|resentful)\b", re.I), "clinical", 1),
    (re.compile(r"\b(lonely|alone|unseen|invisible|abandoned)\b", re.I), "clinical", 3),
    (re.compile(r"\b(remember when|reminds me of|back when|growing up)\b", re.I), "clinical", 2),
    (re.compile(r"\b(breakthrough|realize[ds]?|insight|i see now|i understand)\b", re.I), "coaching", 3),
    (re.compile(r"\b(pattern|cycle|always do|keep doing|every time)\b", re.I), "clinical", 2),
    (re.compile(r"\b(trust|safe|safety|secure|connection)\b", re.I), "clinical", 1),
    (re.compile(r"\b(trauma|traumatic|triggered|wounded|wound)\b", re.I), "clinical", 3),
    (re.compile(r"\b(manipulat\w*|controlling|gaslight\w*|toxic)\b", re.I), "clinical", 2),
    (re.compile(r"\b(sad|sadness|crying|tears|cry me|super sad|heartbroken)\b", re.I), "clinical", 2),
    (re.compile(r"\b(not happy|unhappy|miserable|depressed|hopeless)\b", re.I), "clinical", 2),
    (re.compile(r"\b(hurt|hurting|painful|pain|sting|stings)\b", re.I), "clinical", 2),
    (re.compile(r"\b(mother|father|mom|dad|parent|childhood|grew up|bullied)\b", re.I), "clinical", 2),
    (re.compile(r"\b(projec\w+|deflect\w*)\b", re.I), "clinical", 1),
    (re.compile(r"\b(empathy|empathize|compassion|understanding)\b", re.I), "clinical", 1),
    (re.compile(r"\b(wtf|fuck|shit|damn|hell)\b", re.I), "clinical", 1),
    (re.compile(r"\b(divorce|separati\w+|leave me|left me|walked out)\b", re.I), "clinical", 2),
    (re.compile(r"\b(held.{0,10}in|bottled up|never told|kept.{0,10}secret)\b", re.I), "clinical", 3),
    (re.compile(r"\b(menopause|pregnan\w+|miscarriage|infertil\w+|babies)\b", re.I), "clinical", 1),
    (re.compile(r"\b(supposed to|expected to|have to|can't win)\b", re.I), "clinical", 1),
]

_LONG_DISCLOSURE_RE = re.compile(r"\b(i |i'm |i've |my |me |myself)\b", re.I)

_MIN_SCORE = 4
_MIN_USER_LEN = 40


async def recall_crystals_for_context(
    db_pool,
    hardware_id: str,
    max_results: int = 8,
    source: str = "bridge_chat",
    affect_weight: float = 0.0,
) -> str:
    if not db_pool or not hardware_id:
        return ""
    try:
        async with db_pool.acquire() as conn:
            user_uuid = await conn.fetchval(
                "SELECT id FROM users WHERE hardware_id = $1 OR username = $1 OR id::text = $1 LIMIT 1",
                hardware_id,
            )

            # During LIMINAL RESOLVE, widen retrieval to 50 candidates for affect reranking
            user_limit = max(max_results // 2, 2)
            global_limit = max_results - user_limit
            if affect_weight > 0.0:
                user_limit = max(user_limit, 25)
                global_limit = max(global_limit, 25)

            user_crystals = await conn.fetch(
                """
                SELECT id, crystal_text, confidence, domain, metadata
                FROM nate_intelligence_crystals
                WHERE user_id = $1
                  AND confidence >= 0.30
                  AND scope NOT IN ('archived')
                  AND superseded_by IS NULL
                ORDER BY created_at DESC, confidence DESC
                LIMIT $2
                """,
                user_uuid,
                user_limit,
            )

            global_crystals = await conn.fetch(
                """
                SELECT id, crystal_text, confidence, domain, metadata
                FROM nate_intelligence_crystals
                WHERE user_id IS NULL
                  AND confidence >= 0.55
                  AND scope NOT IN ('archived')
                  AND superseded_by IS NULL
                ORDER BY confidence DESC,
                         last_recalled_at DESC NULLS LAST
                LIMIT $1
                """,
                global_limit,
            )

            # Affect reranking during LIMINAL RESOLVE
            if affect_weight > 0.0:
                user_crystals = _rerank_by_affect(list(user_crystals), affect_weight, max_results // 2)
                global_crystals = _rerank_by_affect(list(global_crystals), affect_weight, max_results - max_results // 2)

            # Lazy-fill affect metadata for crystals that lack it
            if affect_weight > 0.0:
                _lazy_fill_ids = []
                for c in list(user_crystals) + list(global_crystals):
                    meta = c.get("metadata") or {}
                    if isinstance(meta, str):
                        try:
                            import json as _json
                            meta = _json.loads(meta)
                        except Exception:
                            meta = {}
                    if meta.get("emotional_valence") is None:
                        _lazy_fill_ids.append((c["id"], c.get("crystal_text", "")))
                if _lazy_fill_ids:
                    import asyncio as _aio
                    _aio.create_task(_lazy_fill_affect_metadata(conn, _lazy_fill_ids))

            # Check for carried_forward LIMINAL state → append anticipatory crystals
            lr_status = await conn.fetchval(
                """SELECT status FROM liminal_resolve_states
                   WHERE user_id = $1 AND status = 'carried_forward'
                   ORDER BY updated_at DESC LIMIT 1""",
                hardware_id,
            )
            anticipatory_section = ""
            if lr_status == "carried_forward":
                anticipatory_section = await retrieve_anticipatory_crystals(
                    hardware_id, db_pool, strip_task_framing=True,
                )

            crystals = list(user_crystals) + list(global_crystals)
            if not crystals:
                return ""

            crystal_ids = [c["id"] for c in crystals]

            await conn.executemany(
                """
                INSERT INTO crystal_recall_log
                    (user_id, crystal_id, source, recalled_at)
                VALUES ($1, $2, $3, NOW())
                """,
                [(hardware_id, cid, source) for cid in crystal_ids],
            )

            await conn.execute(
                """
                UPDATE nate_intelligence_crystals
                SET recall_count = COALESCE(recall_count, 0) + 1,
                    last_recalled_at = NOW(),
                    confidence = GREATEST(confidence, LEAST(confidence + 0.03, 0.95)),
                    updated_at = NOW()
                WHERE id = ANY($1::int[])
                """,
                crystal_ids,
            )

            lines = []
            if user_crystals:
                lines.append(
                    "YOUR PERSONAL MEMORIES (from prior sessions with this person — "
                    "reference naturally, these are their own words):"
                )
                for c in user_crystals:
                    conf = float(c["confidence"]) if c["confidence"] else 0
                    text = (c["crystal_text"] or "")[:300]
                    lines.append(f"- [{c['domain']}] {text} (confidence: {conf:.2f})")
            if global_crystals:
                lines.append(
                    "GENERAL KNOWLEDGE (validated therapeutic insights — "
                    "reference when relevant):"
                )
                for c in global_crystals:
                    conf = float(c["confidence"]) if c["confidence"] else 0
                    text = (c["crystal_text"] or "")[:200]
                    lines.append(f"- [{c['domain']}] {text} (confidence: {conf:.2f})")
            if anticipatory_section:
                lines.append(anticipatory_section)
            return "\n".join(lines)
    except Exception as e:
        logger.warning("crystal_recall_bridge: %s", e)
        return ""


def _rerank_by_affect(crystals: list, affect_weight: float, limit: int) -> list:
    """Rerank crystals by blended semantic + affect score during LIMINAL RESOLVE."""
    try:
        from app.services.liminal_detectors import score_affect
    except ImportError:
        return crystals[:limit]

    scored = []
    for c in crystals:
        conf = float(c.get("confidence") or 0)
        text = c.get("crystal_text") or ""
        affect = score_affect(text)
        affect_score = (
            abs(affect["emotional_valence"]) * 0.3
            + affect["arousal_level"] * 0.4
            + affect["attachment_activation"] * 0.3
        )
        blended = conf * (1.0 - affect_weight) + affect_score * affect_weight
        scored.append((blended, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:limit]]


async def _lazy_fill_affect_metadata(conn, crystal_id_text_pairs: list) -> None:
    """Background: compute and store affect metadata for crystals missing it."""
    try:
        from app.services.liminal_detectors import score_affect
        import json as _json
        for cid, text in crystal_id_text_pairs[:50]:
            affect = score_affect(text)
            await conn.execute(
                """UPDATE nate_intelligence_crystals
                   SET metadata = COALESCE(metadata, '{}'::jsonb) ||
                       $1::jsonb
                   WHERE id = $2""",
                _json.dumps(affect),
                cid,
            )
    except Exception as e:
        logger.warning("crystal_recall_bridge: lazy affect fill: %s", e)


async def retrieve_anticipatory_crystals(
    user_id: str,
    db_pool,
    strip_task_framing: bool = False,
) -> str:
    """Retrieve anticipatory crystals stored by the Subconscious Engine."""
    if not db_pool or not user_id:
        return ""
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT crystal_text, metadata, domain
                   FROM nate_intelligence_crystals
                   WHERE metadata->>'anticipatory' = 'true'
                     AND metadata->>'target_user_id' = $1
                     AND created_at > NOW() - INTERVAL '14 days'
                     AND scope NOT IN ('archived')
                   ORDER BY created_at DESC
                   LIMIT 5""",
                user_id,
            )
            if not rows:
                return ""

            label = "[RELATED ASSOCIATIONS]" if strip_task_framing else "[PREPARED ASSOCIATIONS]"
            lines = [label]
            for r in rows:
                text = (r["crystal_text"] or "")[:300]
                if strip_task_framing:
                    import re as _re
                    text = _re.sub(
                        r"(?i)\b(for task \d+|feelings work|mismatch evidence|"
                        r"befriend|anchoring|replaying)\b[:\-]*\s*",
                        "", text,
                    ).strip()
                lines.append(f"- {text}")
            return "\n".join(lines)
    except Exception as e:
        logger.warning("crystal_recall_bridge: anticipatory recall: %s", e)
        return ""


async def crystallize_from_conversation(
    db_pool,
    hardware_id: str,
    user_text: str,
    nate_response: str,
    user_name: str = "",
    domain: str = "clinical",
    min_score: int = _MIN_SCORE,
    origin_surface: str = "bridge_chat",
) -> None:
    """
    Extract a user-scoped crystal from a conversation turn when the
    exchange contains enough therapeutic signal.

    Heuristic-only (no LLM call) so it adds zero latency.
    Low initial confidence (0.50) — the backend crystallizer can
    validate and promote later.  Deduplication via content_hash.
    """
    if not db_pool or not hardware_id:
        return
    if len(user_text) < _MIN_USER_LEN:
        return

    score = 0
    matched_domain = domain
    for pattern, pat_domain, weight in _CRYSTAL_SIGNALS:
        if pattern.search(user_text):
            score += weight
            if weight >= 3:
                matched_domain = pat_domain

    if len(user_text) > 200 and _LONG_DISCLOSURE_RE.search(user_text):
        score += 2

    if score < min_score:
        return

    # Build concise crystal text from user disclosure + Nate's reflection
    user_snippet = user_text[:300].strip()
    nate_snippet = nate_response[:200].strip() if nate_response else ""

    name_tag = user_name or hardware_id[:12]
    crystal_text = (
        f"{name_tag} expressed: \"{user_snippet}\""
    )
    if nate_snippet:
        crystal_text += f" — Nate reflected: \"{nate_snippet}\""

    content_hash = hashlib.sha256(crystal_text.encode()).hexdigest()

    try:
        async with db_pool.acquire() as conn:
            user_uuid = await conn.fetchval(
                "SELECT id FROM users WHERE hardware_id = $1 OR username = $1 OR id::text = $1 LIMIT 1",
                hardware_id,
            )

            await conn.execute(
                """
                INSERT INTO nate_intelligence_crystals
                    (crystal_text, domain, scope, topics, source_count,
                     generation, confidence, content_hash, user_id, origin_surface)
                VALUES ($1, $2, 'user', '{}'::text[], 1, 0, 0.50, $3, $4, $5)
                ON CONFLICT (content_hash) DO NOTHING
                """,
                crystal_text, matched_domain, content_hash, user_uuid, origin_surface,
            )
            logger.info(
                "crystal_bridge: forged crystal for %s (score=%d, domain=%s)",
                name_tag, score, matched_domain,
            )
    except Exception as e:
        logger.warning("crystallize_from_conversation: %s", e)

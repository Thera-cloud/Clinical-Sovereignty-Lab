"""
Bridge-side crystal recall + crystallization pipeline.

Uses the bridge's existing db_pool (no HTTP calls to backend).
- recall: retrieves user-scoped + global crystals, logs recalls, reinforces
- crystallize: extracts new user-scoped crystals from conversations
"""
import hashlib
import logging
import random as _rnd
import re
from datetime import datetime, timezone

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

_NATE_THERAPEUTIC_RE = re.compile(
    r"\b(i hear you|what.{0,10}coming up|tell me more|sounds like|it makes sense|"
    r"that.{0,10}painful|let.{0,10}sit with|notice|what.{0,10}feels like|"
    r"i.{0,5}curious|when you say|part of you|underneath|what.{0,10}need)\b", re.I
)

_MIN_SCORE = 4
_MIN_SCORE_VOICE = 2
_MIN_USER_LEN = 40
_MIN_USER_LEN_VOICE = 15

# Global crystal cache (5-min TTL) — avoids repeated 21K+ row scans
_global_crystal_cache: dict = {"rows": [], "expires": 0.0}
_GLOBAL_CACHE_TTL = 300.0  # seconds

# Two-tier deep recall cache — keyed by user_id, 5-min TTL
_deep_recall_cache: dict[str, list] = {}
_deep_recall_expiry: dict[str, float] = {}
_DEEP_RECALL_TTL = 300.0  # seconds


async def _fast_recall_crystals(conn, user_uuid, query_text: str, max_user: int = 5, max_global: int = 3) -> tuple[list, list, set]:
    """Tier 1: single batched CTE for user crystals + cached globals. Target <500ms."""
    import time as _t
    _t0 = _t.monotonic()
    _has_query = bool(query_text and len(query_text.strip()) >= 12)
    _seen_ids: set = set()
    user_crystals = []

    if user_uuid:
        if _has_query:
            rows = await conn.fetch(
                """
                WITH topic_matched AS (
                    SELECT id, crystal_text, confidence, domain, metadata
                    FROM nate_intelligence_crystals
                    WHERE user_id = $1
                      AND confidence >= 0.30
                      AND scope NOT IN ('archived')
                      AND superseded_by IS NULL
                      AND to_tsvector('english', crystal_text) @@ plainto_tsquery('english', $2)
                    ORDER BY ts_rank(to_tsvector('english', crystal_text),
                                     plainto_tsquery('english', $2)) DESC
                    LIMIT 3
                ),
                recent_user AS (
                    SELECT id, crystal_text, confidence, domain, metadata
                    FROM nate_intelligence_crystals
                    WHERE user_id = $1
                      AND confidence >= 0.30
                      AND scope NOT IN ('archived')
                      AND superseded_by IS NULL
                      AND id NOT IN (SELECT id FROM topic_matched)
                    ORDER BY created_at DESC, confidence DESC
                    LIMIT 2
                )
                SELECT *, 'topic' as source FROM topic_matched
                UNION ALL
                SELECT *, 'recent' as source FROM recent_user
                """,
                user_uuid, query_text.strip()[:200],
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, crystal_text, confidence, domain, metadata, 'recent' as source
                FROM nate_intelligence_crystals
                WHERE user_id = $1
                  AND confidence >= 0.30
                  AND scope NOT IN ('archived')
                  AND superseded_by IS NULL
                ORDER BY created_at DESC, confidence DESC
                LIMIT $2
                """,
                user_uuid, max_user,
            )
        for r in rows:
            if r["id"] not in _seen_ids and len(user_crystals) < max_user:
                user_crystals.append(r)
                _seen_ids.add(r["id"])

    global_crystals = []
    _now = _t.monotonic()
    if _global_crystal_cache["expires"] < _now or not _global_crystal_cache["rows"]:
        _g_top_all = await conn.fetch(
            "SELECT id, crystal_text, confidence, domain, metadata "
            "FROM nate_intelligence_crystals "
            "WHERE user_id IS NULL AND confidence >= 0.55 "
            "AND scope NOT IN ('archived') AND superseded_by IS NULL "
            "ORDER BY confidence DESC, last_recalled_at DESC NULLS LAST LIMIT 50",
        )
        _global_crystal_cache["rows"] = [dict(r) for r in _g_top_all]
        _global_crystal_cache["expires"] = _now + _GLOBAL_CACHE_TTL
    for r in _global_crystal_cache["rows"]:
        if r["id"] not in _seen_ids and len(global_crystals) < max_global:
            global_crystals.append(r)
            _seen_ids.add(r["id"])

    _elapsed = (_t.monotonic() - _t0) * 1000
    logger.info("[CRYSTAL FAST] user_cte: %.1fms, total: %.1fms (%d user + %d global)",
                _elapsed, _elapsed, len(user_crystals), len(global_crystals))
    return user_crystals, global_crystals, _seen_ids


async def _deep_recall_crystals(db_pool, hardware_id: str, user_uuid, query_text: str,
                                 seen_ids: set, affect_weight: float = 0.0) -> None:
    """Tier 2: background task. Cold-start, clinical DNA, liminal, patterns. Stores in cache."""
    import time as _t
    _t0 = _t.monotonic()
    cache_key = str(user_uuid or hardware_id)
    deep_user = []
    deep_clinical_dna = []
    deep_anticipatory = ""
    _has_query = bool(query_text and len(query_text.strip()) >= 12)
    try:
        async with db_pool.acquire() as conn:
            _t_cold = _t.monotonic()
            if user_uuid:
                _u_cold_cnt = await conn.fetchval(
                    "SELECT count(*) FROM nate_intelligence_crystals "
                    "WHERE user_id = $1 AND confidence >= 0.30 AND scope NOT IN ('archived') "
                    "AND superseded_by IS NULL AND (recall_count IS NULL OR recall_count = 0) "
                    "AND created_at > NOW() - INTERVAL '180 days'",
                    user_uuid,
                )
                if _u_cold_cnt > 0:
                    _cold = await conn.fetch(
                        "SELECT id, crystal_text, confidence, domain, metadata "
                        "FROM nate_intelligence_crystals "
                        "WHERE user_id = $1 AND confidence >= 0.30 AND scope NOT IN ('archived') "
                        "AND superseded_by IS NULL AND (recall_count IS NULL OR recall_count = 0) "
                        "AND created_at > NOW() - INTERVAL '180 days' "
                        "ORDER BY id OFFSET $2 LIMIT 1",
                        user_uuid, _rnd.randrange(max(_u_cold_cnt, 1)),
                    )
                    for r in _cold:
                        if r["id"] not in seen_ids:
                            deep_user.append(r)
            _ms_cold = (_t.monotonic() - _t_cold) * 1000

            if _has_query:
                _g_cold_cnt = await conn.fetchval(
                    "SELECT count(*) FROM nate_intelligence_crystals "
                    "WHERE user_id IS NULL AND confidence >= 0.55 AND scope NOT IN ('archived') "
                    "AND superseded_by IS NULL AND (recall_count IS NULL OR recall_count = 0)",
                )
                if _g_cold_cnt > 0:
                    _g_cold = await conn.fetch(
                        "SELECT id, crystal_text, confidence, domain, metadata "
                        "FROM nate_intelligence_crystals "
                        "WHERE user_id IS NULL AND confidence >= 0.55 AND scope NOT IN ('archived') "
                        "AND superseded_by IS NULL AND (recall_count IS NULL OR recall_count = 0) "
                        "ORDER BY id OFFSET $1 LIMIT 1",
                        _rnd.randrange(max(_g_cold_cnt, 1)),
                    )
                    for r in _g_cold:
                        if r["id"] not in seen_ids:
                            deep_user.append(r)

                _g_topic = await conn.fetch(
                    """
                    SELECT id, crystal_text, confidence, domain, metadata
                    FROM nate_intelligence_crystals
                    WHERE user_id IS NULL
                      AND confidence >= 0.55
                      AND scope NOT IN ('archived')
                      AND superseded_by IS NULL
                      AND to_tsvector('english', crystal_text) @@ plainto_tsquery('english', $1)
                    ORDER BY ts_rank(to_tsvector('english', crystal_text),
                                     plainto_tsquery('english', $1)) DESC
                    LIMIT 3
                    """,
                    query_text.strip()[:200],
                )
                for r in _g_topic:
                    if r["id"] not in seen_ids:
                        deep_user.append(r)

            _t_dna = _t.monotonic()
            _dna_cnt = await conn.fetchval(
                "SELECT count(*) FROM nate_intelligence_crystals "
                "WHERE user_id IS NULL AND confidence >= 0.85 AND scope NOT IN ('archived') "
                "AND superseded_by IS NULL AND origin_surface IN ('growth_engine', 'clinical_edge_seed')",
            )
            if _dna_cnt > 0:
                _dna_rows = await conn.fetch(
                    "SELECT id, crystal_text, confidence, domain, metadata "
                    "FROM nate_intelligence_crystals "
                    "WHERE user_id IS NULL AND confidence >= 0.85 AND scope NOT IN ('archived') "
                    "AND superseded_by IS NULL AND origin_surface IN ('growth_engine', 'clinical_edge_seed') "
                    "ORDER BY id OFFSET $1 LIMIT 2",
                    _rnd.randrange(max(_dna_cnt, 1)),
                )
                for r in _dna_rows:
                    if r["id"] not in seen_ids:
                        deep_clinical_dna.append(r)
            _ms_dna = (_t.monotonic() - _t_dna) * 1000

            _t_lim = _t.monotonic()
            lr_status = await conn.fetchval(
                """SELECT status FROM liminal_resolve_states
                   WHERE user_id = $1 AND status = 'carried_forward'
                   ORDER BY updated_at DESC LIMIT 1""",
                hardware_id,
            )
            if lr_status == "carried_forward":
                deep_anticipatory = await retrieve_anticipatory_crystals(
                    hardware_id, db_pool, strip_task_framing=True,
                )
            _ms_lim = (_t.monotonic() - _t_lim) * 1000

        _deep_recall_cache[cache_key] = {
            "user": [dict(r) for r in deep_user],
            "clinical_dna": [dict(r) for r in deep_clinical_dna],
            "anticipatory": deep_anticipatory,
        }
        _deep_recall_expiry[cache_key] = _t.monotonic() + _DEEP_RECALL_TTL

        _total = (_t.monotonic() - _t0) * 1000
        logger.info("[CRYSTAL DEEP] cold_start: %.1fms, clinical_dna: %.1fms, liminal: %.1fms, total: %.1fms (%d crystals)",
                    _ms_cold, _ms_dna, _ms_lim, _total,
                    len(deep_user) + len(deep_clinical_dna))
    except Exception as e:
        logger.warning("crystal_recall_bridge: deep recall: %s", e)


def _get_deep_cache(user_uuid, hardware_id: str) -> dict | None:
    """Return deep recall cache if warm and not expired."""
    import time as _t
    cache_key = str(user_uuid or hardware_id)
    exp = _deep_recall_expiry.get(cache_key, 0.0)
    if _t.monotonic() < exp and cache_key in _deep_recall_cache:
        return _deep_recall_cache[cache_key]
    return None


async def recall_crystals_for_context(
    db_pool,
    hardware_id: str,
    max_results: int = 8,
    source: str = "bridge_chat",
    affect_weight: float = 0.0,
    query_text: str = "",
) -> str:
    if not db_pool or not hardware_id:
        return ""
    try:
        async with db_pool.acquire() as conn:
            user_uuid = await conn.fetchval(
                "SELECT id FROM users WHERE hardware_id = $1 OR username = $1 OR id::text = $1 LIMIT 1",
                hardware_id,
            )

            user_limit = max(max_results // 2, 2)
            global_limit = max_results - user_limit

            user_crystals, global_crystals, _seen_ids = await _fast_recall_crystals(
                conn, user_uuid, query_text, max_user=user_limit, max_global=global_limit,
            )

        deep_cache = _get_deep_cache(user_uuid, hardware_id)
        clinical_dna = []
        anticipatory_section = ""
        deep_extras = []

        if deep_cache:
            for r in deep_cache.get("clinical_dna", []):
                if r["id"] not in _seen_ids:
                    clinical_dna.append(r)
                    _seen_ids.add(r["id"])
            for r in deep_cache.get("user", []):
                if r["id"] not in _seen_ids:
                    deep_extras.append(r)
                    _seen_ids.add(r["id"])
            anticipatory_section = deep_cache.get("anticipatory", "")

        if affect_weight > 0.0:
            all_user = list(user_crystals) + deep_extras
            user_crystals = _rerank_by_affect(all_user, affect_weight, max_results // 2)
            global_crystals = _rerank_by_affect(list(global_crystals), affect_weight, max_results - max_results // 2)
        else:
            user_crystals = list(user_crystals) + deep_extras

        crystals = user_crystals + clinical_dna + list(global_crystals)
        if not crystals:
            return ""

        crystal_ids = [c["id"] for c in crystals]

        import asyncio as _aio
        _aio.create_task(_reinforce_recalled_crystals(db_pool, hardware_id, crystal_ids, source))
        _aio.create_task(_deep_recall_crystals(db_pool, hardware_id, user_uuid, query_text, _seen_ids, affect_weight))

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
        if clinical_dna:
            lines.append(
                "CLINICAL DNA (your lived growth lessons — these define "
                "HOW you respond, follow them precisely):"
            )
            for c in clinical_dna:
                conf = float(c["confidence"]) if c["confidence"] else 0
                text = (c["crystal_text"] or "")[:300]
                lines.append(f"- {text} (confidence: {conf:.2f})")
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


async def _reinforce_recalled_crystals(db_pool, hardware_id: str, crystal_ids: list, source: str) -> None:
    """Background: log recall + update recall_count/confidence + co-activation."""
    try:
        async with db_pool.acquire() as conn:
            await conn.executemany(
                "INSERT INTO crystal_recall_log (user_id, crystal_id, source, recalled_at) VALUES ($1, $2, $3, NOW())",
                [(hardware_id, cid, source) for cid in crystal_ids],
            )
            await conn.execute(
                "UPDATE nate_intelligence_crystals SET recall_count = COALESCE(recall_count, 0) + 1, "
                "last_recalled_at = NOW(), confidence = GREATEST(confidence, LEAST(confidence + 0.03, 0.95)), "
                "updated_at = NOW() WHERE id = ANY($1::int[])",
                crystal_ids,
            )
        if len(crystal_ids) >= 2:
            await _record_co_activation(db_pool, crystal_ids, source)
    except Exception as e:
        logger.warning("crystal_recall_bridge: reinforcement write: %s", e)


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


async def _record_co_activation(db_pool, crystal_ids: list, source: str) -> None:
    """Background: record which crystals were recalled together (co-activation).

    Populates crystal_co_activation_events for graph analysis and
    updates crystal_edges with co_activation edge type.
    """
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, LEFT(content_hash, 16) as hash_prefix
                   FROM nate_intelligence_crystals
                   WHERE id = ANY($1::int[])
                     AND content_hash IS NOT NULL AND content_hash != ''""",
                crystal_ids,
            )
            hashes = sorted(set(r["hash_prefix"] for r in rows if r["hash_prefix"]))
            if len(hashes) < 2:
                return

            now = datetime.now(timezone.utc)
            bucket = now.replace(minute=(now.minute // 10) * 10, second=0, microsecond=0)
            pairs = []
            for i, a in enumerate(hashes):
                for b in hashes[i + 1:]:
                    pairs.append((source, a, b, bucket))

            await conn.executemany(
                """INSERT INTO crystal_co_activation_events
                       (source, crystal_a, crystal_b, time_bucket, event_count, last_seen_at, created_at)
                   VALUES ($1, $2, $3, $4, 1, NOW(), NOW())
                   ON CONFLICT (source, COALESCE(session_id, ''), COALESCE(call_sid, ''), crystal_a, crystal_b, time_bucket)
                   DO UPDATE SET event_count = crystal_co_activation_events.event_count + 1,
                                 last_seen_at = NOW()""",
                pairs,
            )

            edge_pairs = [(a, b, source) for _, a, b, _ in pairs]
            await conn.executemany(
                """INSERT INTO crystal_edges
                       (crystal_a_hash, crystal_b_hash, similarity, edge_type,
                        co_activation_count, last_co_activated_at, source)
                   VALUES ($1, $2, 0.0, 'co_activation', 1, NOW(), $3)
                   ON CONFLICT (crystal_a_hash, crystal_b_hash)
                   DO UPDATE SET co_activation_count = crystal_edges.co_activation_count + 1,
                                 last_co_activated_at = NOW()""",
                edge_pairs,
            )
    except Exception as e:
        logger.warning("crystal_recall_bridge: co-activation recording: %s", e)


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
    is_voice = origin_surface == "voice_call"
    effective_min_len = _MIN_USER_LEN_VOICE if is_voice else _MIN_USER_LEN
    if len(user_text) < effective_min_len:
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
    # QUANTUM-CRYSTAL-ARCH: boost from shorter first-person disclosures
    elif len(user_text) > 80 and _LONG_DISCLOSURE_RE.search(user_text):
        score += 1

    # QUANTUM-CRYSTAL-ARCH: if Nate reflected therapeutically, the exchange matters
    if nate_response and _NATE_THERAPEUTIC_RE.search(nate_response):
        score += 2

    effective_min_score = _MIN_SCORE_VOICE if is_voice else min_score
    if score < effective_min_score:
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
                "crystal_bridge: forged crystal for %s (score=%d, domain=%s, surface=%s)",
                name_tag, score, matched_domain, origin_surface,
            )

        # QUANTUM-CRYSTAL-ARCH: Vectorize embedding so crystal is semantically searchable
        try:
            from app.services.vectorize_service import index_wisdom, is_vectorize_configured
            if is_vectorize_configured():
                await index_wisdom(
                    user_id=str(user_uuid) if user_uuid else "nate_crystal",
                    wisdom_id=f"crystal_{content_hash[:16]}",
                    insight_type=f"crystal_{matched_domain}",
                    content=crystal_text,
                    source=origin_surface,
                    domain=matched_domain,
                )
        except Exception as _vec_err:
            logger.debug("crystal_bridge: vectorize failed (non-fatal): %s", _vec_err)
    except Exception as e:
        logger.warning("crystallize_from_conversation: %s", e)


async def crystallize_session_summary(
    db_pool,
    hardware_id: str,
    turns: list,
    user_name: str = "",
    origin_surface: str = "bridge_chat",
    session_id: str = "",
) -> int:
    """
    Create a comprehensive session-level crystal from multiple conversation turns.

    Unlike per-turn crystallization which captures individual disclosures,
    this captures the session arc: themes across turns, emotional trajectory,
    and key commitments. Returns number of crystals created.

    QUANTUM-CRYSTAL-ARCH: session summary crystals are the primary mechanism
    for converting lived therapeutic interaction into retrievable wisdom.
    """
    if not db_pool or not hardware_id or not turns:
        return 0

    name_tag = user_name or hardware_id[:12]
    created = 0

    try:
        async with db_pool.acquire() as conn:
            user_uuid = await conn.fetchval(
                "SELECT id FROM users WHERE hardware_id = $1 OR username = $1 OR id::text = $1 LIMIT 1",
                hardware_id,
            )

            user_texts = []
            nate_texts = []
            for t in turns:
                u = t.get("user_text") or t.get("text") or ""
                a = t.get("ai_text") or t.get("nate_text") or t.get("assistant_text") or ""
                if u:
                    user_texts.append(u.strip())
                if a:
                    nate_texts.append(a.strip())

            if not user_texts:
                return 0

            all_user = " ".join(user_texts)

            themes = []
            for pattern, pat_domain, weight in _CRYSTAL_SIGNALS:
                if pattern.search(all_user):
                    match_text = pattern.pattern.replace(r"\b", "").replace("(", "").replace(")", "")
                    themes.append(match_text.split("|")[0].strip())
            themes = themes[:8]

            session_crystal = (
                f"SESSION SUMMARY ({name_tag}, {len(user_texts)} turns, {origin_surface}): "
                f"Client discussed: {all_user[:600]}."
            )
            if nate_texts:
                session_crystal += f" Nate reflected: {' '.join(nate_texts)[:400]}."
            if themes:
                session_crystal += f" Themes: {', '.join(themes)}."

            content_hash = hashlib.sha256(session_crystal.encode()).hexdigest()

            await conn.execute(
                """INSERT INTO nate_intelligence_crystals
                    (crystal_text, domain, scope, topics, source_count,
                     generation, confidence, content_hash, user_id, origin_surface)
                VALUES ($1, 'clinical', 'user', $2, $3, 0, 0.55, $4, $5, $6)
                ON CONFLICT (content_hash) DO NOTHING""",
                session_crystal,
                themes if themes else [],
                len(user_texts),
                content_hash,
                user_uuid,
                origin_surface,
            )
            created += 1
            logger.info(
                "crystal_bridge: session summary crystal for %s (%d turns, surface=%s)",
                name_tag, len(user_texts), origin_surface,
            )

            emotional_turns = []
            for u in user_texts:
                e_score = 0
                for pattern, _, weight in _CRYSTAL_SIGNALS:
                    if pattern.search(u):
                        e_score += weight
                if e_score >= 3 or (len(u) > 100 and _LONG_DISCLOSURE_RE.search(u)):
                    emotional_turns.append(u)

            for i, key_turn in enumerate(emotional_turns[:5]):
                key_crystal = f"{name_tag} disclosed: \"{key_turn[:400]}\""
                key_hash = hashlib.sha256(key_crystal.encode()).hexdigest()
                result = await conn.execute(
                    """INSERT INTO nate_intelligence_crystals
                        (crystal_text, domain, scope, topics, source_count,
                         generation, confidence, content_hash, user_id, origin_surface)
                    VALUES ($1, 'clinical', 'user', '{}', 1, 0, 0.50, $2, $3, $4)
                    ON CONFLICT (content_hash) DO NOTHING""",
                    key_crystal, key_hash, user_uuid, origin_surface,
                )
                if "INSERT 0 1" in str(result):
                    created += 1

        try:
            from app.services.vectorize_service import index_wisdom, is_vectorize_configured
            if is_vectorize_configured():
                await index_wisdom(
                    user_id=str(user_uuid) if user_uuid else "nate_crystal",
                    wisdom_id=f"crystal_{content_hash[:16]}",
                    insight_type=f"session_summary_{origin_surface}",
                    content=session_crystal,
                    source=origin_surface,
                    domain="clinical",
                )
        except Exception as _vec_err:
            logger.debug("crystal_bridge: session vectorize non-fatal: %s", _vec_err)

    except Exception as e:
        logger.warning("crystallize_session_summary: %s", e)

    return created

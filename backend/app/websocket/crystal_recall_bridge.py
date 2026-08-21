"""
Bridge-side crystal recall + crystallization pipeline.

Uses the bridge's existing db_pool (no HTTP calls to backend).
- recall: retrieves user-scoped + global crystals, logs recalls, reinforces
- crystallize: extracts new user-scoped crystals from conversations
"""
import asyncio
import hashlib
import json
import logging
import random as _rnd
import re
from datetime import datetime, timezone
from typing import Optional

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

# Plan v1.3 Phase 5 Note 2c — engineer-authored sensitive seed crystals are
# inserted with crystal_status='awaiting_clinician_authoring'. They MUST NOT
# surface in production recall until a clinician reviews and flips the row to
# 'production'. The OR NULL clause preserves backward compat for legacy rows
# (added in migration 211 with default 'production'); pre-migration rows have
# NULL crystal_status and remain recallable. New seed inserts are explicit.
_PRODUCTION_STATUS_FILTER = (
    "AND (crystal_status IS NULL OR crystal_status = 'production')"
)

# Global crystal cache (5-min TTL) — avoids repeated 21K+ row scans
_global_crystal_cache: dict = {"rows": [], "expires": 0.0}
_GLOBAL_CACHE_TTL = 300.0  # seconds

# Two-tier deep recall cache — keyed by user_id, 5-min TTL
_deep_recall_cache: dict[str, list] = {}
_deep_recall_expiry: dict[str, float] = {}
_DEEP_RECALL_TTL = 300.0  # seconds

# QUANTUM-CRYSTAL-ARCH: Tier 1 enrichment knobs — env-gated, defaults preserve
# pre-existing behavior exactly (unset env = no change).
import os as _os
_RECALL_MAX_ENV = (_os.getenv("BRIDGE_RECALL_MAX_RESULTS", "") or "").strip()
_USER_SNIPPET = int(_os.getenv("BRIDGE_RECALL_USER_SNIPPET", "300"))
_GLOBAL_SNIPPET = int(_os.getenv("BRIDGE_RECALL_GLOBAL_SNIPPET", "200"))
_SYNC_DEEP_RECALL = (_os.getenv("BRIDGE_SYNC_DEEP_RECALL", "") or "").strip().lower() in ("1", "true", "yes", "on")
_SYNC_DEEP_TIMEOUT_S = float(_os.getenv("BRIDGE_SYNC_DEEP_TIMEOUT_S", "1.8"))
_VALIDATOR_FILTER_RECALL = (_os.getenv("BRIDGE_VALIDATOR_FILTER_RECALL", "") or "").strip().lower() in ("1", "true", "yes", "on")

# QUANTUM-CRYSTAL-ARCH: L3a — outcome-weighted recall rank. Uses crystal_outcome_view
# (C_emo attributed to prior recalls). Does NOT UPDATE confidence for clinical/defense
# (RED stays CEO-apply only via crystal_outcome_apply). Default ON.
_OUTCOME_RECALL_RANK = (_os.getenv("ENABLE_CRYSTAL_OUTCOME_RECALL_RANK", "true") or "").strip().lower() not in (
    "0", "false", "no", "off",
)
_OUTCOME_RECALL_MIN_SAMPLE = int(_os.getenv("CRYSTAL_OUTCOME_RECALL_MIN_SAMPLE", "3"))
_OUTCOME_RECALL_BLEND = float(_os.getenv("CRYSTAL_OUTCOME_RECALL_BLEND", "0.35"))

# QUANTUM-CRYSTAL-ARCH: Commit 2 (crystal attribution) — inert-metadata flag,
# default True (it only attaches an extra attribute to the returned string;
# it changes no behavior for callers that don't read it).
_ENABLE_CRYSTAL_ATTRIBUTION = (_os.getenv("ENABLE_CRYSTAL_ATTRIBUTION", "true") or "").strip().lower() not in ("0", "false", "no", "off")


class _AttributedContext(str):
    """str subclass that carries the recalled crystal ids as `.crystal_ids`.

    Identical to a plain str for every existing caller (equality, `+`,
    f-string interpolation, `if ctx:` truthiness). Only new code that reads
    `.crystal_ids` sees the extra data — no caller signature changed.
    """
    crystal_ids: list = []
    crystal_scopes: list = []  # QUANTUM-CRYSTAL-ARCH — Phase 5b


def scopes_from_recall_context(ctx) -> list:
    """QUANTUM-CRYSTAL-ARCH: Phase 5b scopes off recall return (str or attributed)."""
    try:
        return list(getattr(ctx, "crystal_scopes", None) or [])[:50]
    except Exception:
        return []


try:
    from .bridge_enrichment import (
        is_memory_turn as _enr_is_memory_turn,
        lexical_rerank_globals as _enr_rerank_globals,
    )
except Exception:
    try:
        from bridge_enrichment import (  # type: ignore
            is_memory_turn as _enr_is_memory_turn,
            lexical_rerank_globals as _enr_rerank_globals,
        )
    except Exception:
        _enr_is_memory_turn = None
        _enr_rerank_globals = None


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
                    SELECT id, crystal_text, confidence, domain, metadata, scope
                    FROM nate_intelligence_crystals
                    WHERE user_id = $1
                      AND confidence >= 0.30
                      AND (scope = 'user' OR scope LIKE 'user:%')
                      AND superseded_by IS NULL
                      AND (crystal_status IS NULL OR crystal_status = 'production')
                      AND to_tsvector('english', crystal_text) @@ plainto_tsquery('english', $2)
                    ORDER BY ts_rank(to_tsvector('english', crystal_text),
                                     plainto_tsquery('english', $2)) DESC
                    LIMIT 3
                ),
                recent_user AS (
                    SELECT id, crystal_text, confidence, domain, metadata, scope
                    FROM nate_intelligence_crystals
                    WHERE user_id = $1
                      AND confidence >= 0.30
                      AND (scope = 'user' OR scope LIKE 'user:%')
                      AND superseded_by IS NULL
                      AND (crystal_status IS NULL OR crystal_status = 'production')
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
                SELECT id, crystal_text, confidence, domain, metadata, scope, 'recent' as source
                FROM nate_intelligence_crystals
                WHERE user_id = $1
                  AND confidence >= 0.30
                  AND (scope = 'user' OR scope LIKE 'user:%')
                  AND superseded_by IS NULL
                  AND (crystal_status IS NULL OR crystal_status = 'production')
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
            "SELECT id, crystal_text, confidence, domain, metadata, scope "
            "FROM nate_intelligence_crystals "
            "WHERE user_id IS NULL AND confidence >= 0.55 "
            "AND scope = 'global' AND superseded_by IS NULL "
            "AND (crystal_status IS NULL OR crystal_status = 'production') "
            "ORDER BY confidence DESC, last_recalled_at DESC NULLS LAST LIMIT 50",
        )
        _global_crystal_cache["rows"] = [dict(r) for r in _g_top_all]
        _global_crystal_cache["expires"] = _now + _GLOBAL_CACHE_TTL
    # QUANTUM-CRYSTAL-ARCH: Tier 1 — lexical re-rank of the cached global pool
    # against the current turn (falls back to confidence order when unavailable).
    if _enr_rerank_globals is not None:
        try:
            global_crystals = _enr_rerank_globals(
                _global_crystal_cache["rows"], query_text, max_global, _seen_ids,
            )
        except Exception:
            global_crystals = []
    if not global_crystals:
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
                    "WHERE user_id = $1 AND confidence >= 0.30 AND (scope = 'user' OR scope LIKE 'user:%') "
                    "AND superseded_by IS NULL AND (recall_count IS NULL OR recall_count = 0) "
                    "AND (crystal_status IS NULL OR crystal_status = 'production') "
                    "AND created_at > NOW() - INTERVAL '180 days'",
                    user_uuid,
                )
                if _u_cold_cnt > 0:
                    _cold = await conn.fetch(
                        "SELECT id, crystal_text, confidence, domain, metadata, scope "
                        "FROM nate_intelligence_crystals "
                        "WHERE user_id = $1 AND confidence >= 0.30 AND (scope = 'user' OR scope LIKE 'user:%') "
                        "AND superseded_by IS NULL AND (recall_count IS NULL OR recall_count = 0) "
                        "AND (crystal_status IS NULL OR crystal_status = 'production') "
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
                    "WHERE user_id IS NULL AND confidence >= 0.55 AND scope = 'global' "
                    "AND superseded_by IS NULL AND (recall_count IS NULL OR recall_count = 0) "
                    "AND (crystal_status IS NULL OR crystal_status = 'production')",
                )
                if _g_cold_cnt > 0:
                    _g_cold = await conn.fetch(
                        "SELECT id, crystal_text, confidence, domain, metadata, scope "
                        "FROM nate_intelligence_crystals "
                        "WHERE user_id IS NULL AND confidence >= 0.55 AND scope = 'global' "
                        "AND superseded_by IS NULL AND (recall_count IS NULL OR recall_count = 0) "
                        "AND (crystal_status IS NULL OR crystal_status = 'production') "
                        "ORDER BY id OFFSET $1 LIMIT 1",
                        _rnd.randrange(max(_g_cold_cnt, 1)),
                    )
                    for r in _g_cold:
                        if r["id"] not in seen_ids:
                            deep_user.append(r)

                _g_topic = await conn.fetch(
                    """
                    SELECT id, crystal_text, confidence, domain, metadata, scope
                    FROM nate_intelligence_crystals
                    WHERE user_id IS NULL
                      AND confidence >= 0.55
                      AND scope = 'global'
                      AND superseded_by IS NULL
                      AND (crystal_status IS NULL OR crystal_status = 'production')
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
                "WHERE user_id IS NULL AND confidence >= 0.85 AND scope = 'global' "
                "AND superseded_by IS NULL AND origin_surface IN ('growth_engine', 'clinical_edge_seed') "
                "AND (crystal_status IS NULL OR crystal_status = 'production')",
            )
            if _dna_cnt > 0:
                _dna_rows = await conn.fetch(
                    "SELECT id, crystal_text, confidence, domain, metadata, scope "
                    "FROM nate_intelligence_crystals "
                    "WHERE user_id IS NULL AND confidence >= 0.85 AND scope = 'global' "
                    "AND superseded_by IS NULL AND origin_surface IN ('growth_engine', 'clinical_edge_seed') "
                    "AND (crystal_status IS NULL OR crystal_status = 'production') "
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


def _get_deep_cache(user_uuid, hardware_id: str) -> Optional[dict]:
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
    global_only: bool = False,
) -> str:
    if not db_pool or not hardware_id:
        return ""
    # QUANTUM-CRYSTAL-ARCH: Tier 1 — env override widens recall breadth
    if _RECALL_MAX_ENV:
        try:
            max_results = max(max_results, int(_RECALL_MAX_ENV))
        except ValueError:
            pass
    try:
        # global_only (public trial isolation): never look up a user UUID, never
        # touch the deep-recall/clinical_dna/anticipatory cache — those are all
        # per-person. Trial callers get globals-only, same as a brand-new user.
        if global_only:
            async with db_pool.acquire() as conn:
                user_uuid = None
                user_crystals, global_crystals, _seen_ids = await _fast_recall_crystals(
                    conn, None, query_text, max_user=0, max_global=max_results,
                )
            deep_cache = None
        else:
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

        # QUANTUM-CRYSTAL-ARCH: Tier 1 — on explicit memory turns with a cold
        # deep cache, run deep recall synchronously (bounded) so the answer
        # that references shared history has the deep set available NOW.
        if (
            not global_only and _SYNC_DEEP_RECALL and deep_cache is None
            and _enr_is_memory_turn is not None and _enr_is_memory_turn(query_text)
        ):
            try:
                await asyncio.wait_for(
                    _deep_recall_crystals(db_pool, hardware_id, user_uuid, query_text, _seen_ids, affect_weight),
                    timeout=_SYNC_DEEP_TIMEOUT_S,
                )
                deep_cache = _get_deep_cache(user_uuid, hardware_id)
            except Exception:
                deep_cache = None
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

        # QUANTUM-CRYSTAL-ARCH — Tier-1 D.14b: drop battery-contaminated recall
        try:
            from app.services.six_quotient_battery_quarantine import filter_crystals

            user_crystals = filter_crystals(list(user_crystals))
            clinical_dna = filter_crystals(list(clinical_dna))
            global_crystals = filter_crystals(list(global_crystals))
        except Exception:
            pass

        # QUANTUM-CRYSTAL-ARCH — boost user crystals by PGSD 5D proximity (ACCESS)
        try:
            import os as _os_pgsd
            if (
                not global_only
                and _os_pgsd.environ.get("ENABLE_PGSD_ACCESS", "").lower()
                in ("true", "1", "yes", "on")
                and user_crystals
            ):
                async with db_pool.acquire() as _cprox:
                    _pin = await _cprox.fetchrow(
                        """
                        SELECT d1_valence, d2_arousal, d3_relational,
                               d4_temporal_depth, d5_integration
                        FROM pgsd_snapshots
                        WHERE user_id = $1 OR username = $1
                        ORDER BY computed_at DESC LIMIT 1
                        """,
                        hardware_id,
                    )
                    if _pin and user_crystals:
                        ids = [c["id"] for c in user_crystals if c.get("id")]
                        stamps = await _cprox.fetch(
                            """
                            SELECT id, pgsd_d1, pgsd_d2, pgsd_d3, pgsd_d4, pgsd_d5
                            FROM nate_intelligence_crystals
                            WHERE id = ANY($1::uuid[])
                            """,
                            ids,
                        )
                        by_id = {r["id"]: r for r in stamps}

                        def _dist(c, _by=by_id, _p=_pin):
                            s = _by.get(c["id"])
                            if not s or s.get("pgsd_d1") is None:
                                return 999.0
                            try:
                                return (
                                    (float(s["pgsd_d1"] or 0) - float(_p["d1_valence"] or 0)) ** 2
                                    + (float(s["pgsd_d2"] or 0) - float(_p["d2_arousal"] or 0)) ** 2
                                    + (float(s["pgsd_d3"] or 0) - float(_p["d3_relational"] or 0)) ** 2
                                    + (float(s["pgsd_d4"] or 0) - float(_p["d4_temporal_depth"] or 0)) ** 2
                                    + (float(s["pgsd_d5"] or 0) - float(_p["d5_integration"] or 0)) ** 2
                                )
                            except Exception:
                                return 999.0

                        user_crystals = sorted(list(user_crystals), key=_dist)
        except Exception:
            pass

        # QUANTUM-CRYSTAL-ARCH: L3a — outcome-weighted rank (C_emo attribution).
        # Partition-preserving: personal / clinical-dna / global slots stay separate.
        if _OUTCOME_RECALL_RANK and (user_crystals or clinical_dna or global_crystals):
            try:
                async with db_pool.acquire() as _oconn:
                    if user_crystals:
                        user_crystals = await _rerank_by_outcome(
                            _oconn, list(user_crystals), len(user_crystals),
                        )
                    if clinical_dna:
                        clinical_dna = await _rerank_by_outcome(
                            _oconn, list(clinical_dna), len(clinical_dna),
                        )
                    if global_crystals:
                        global_crystals = await _rerank_by_outcome(
                            _oconn, list(global_crystals), len(global_crystals),
                        )
            except Exception as _ore:
                logger.debug("crystal_recall_bridge: L3a outcome rank skipped: %s", _ore)

        crystals = user_crystals + clinical_dna + list(global_crystals)
        if not crystals:
            return ""

        # QUANTUM-CRYSTAL-ARCH — Slice 4 (Bee HIV+): program isolation filter.
        # When ENABLE_PROGRAM_ISOLATION is on, drop crystals whose program_id
        # is incompatible with the caller (general users can't see program-
        # specific disclosures, and program members can't see other programs).
        # Flag-off = zero behavior change (helper returns input unchanged).
        try:
            from app.services.program_isolation import (
                is_enabled as _prog_enabled,
                get_user_program_id as _prog_user,
                filter_crystals_by_program_async as _prog_filter,
            )
            if _prog_enabled():
                _pid = None if global_only else await _prog_user(db_pool, hardware_id)
                _kept = await _prog_filter(db_pool, list(crystals), _pid)
                _kept_ids = {int(c["id"]) for c in _kept}
                user_crystals = [c for c in user_crystals if int(c["id"]) in _kept_ids]
                clinical_dna = [c for c in clinical_dna if int(c["id"]) in _kept_ids]
                global_crystals = [c for c in global_crystals if int(c["id"]) in _kept_ids]
                crystals = user_crystals + clinical_dna + list(global_crystals)
                if not crystals:
                    return ""
        except Exception as _pe:
            logger.debug("crystal_recall_bridge: program isolation skipped: %s", _pe)

        # QUANTUM-CRYSTAL-ARCH: Tier 1 — Layer 8 factual-grounding filter at
        # recall time (flag-gated). Filtered crystals stay in PG, just not here.
        if _VALIDATOR_FILTER_RECALL:
            try:
                from app.services.nate_response_validator import NateResponseValidator as _NRV
                _clean = _NRV.filter_recalled_crystals([dict(c) for c in crystals])
                _clean_ids = {c.get("id") for c in _clean if isinstance(c, dict)}
                user_crystals = [c for c in user_crystals if c["id"] in _clean_ids]
                clinical_dna = [c for c in clinical_dna if c["id"] in _clean_ids]
                global_crystals = [c for c in global_crystals if c["id"] in _clean_ids]
                crystals = user_crystals + clinical_dna + list(global_crystals)
                if not crystals:
                    return ""
            except Exception as _fe:
                logger.debug("crystal_recall_bridge: validator filter skipped: %s", _fe)

        crystal_ids = [c["id"] for c in crystals]

        import asyncio as _aio
        _aio.create_task(_reinforce_recalled_crystals(db_pool, hardware_id, crystal_ids, source))
        if not global_only:
            _aio.create_task(_deep_recall_crystals(db_pool, hardware_id, user_uuid, query_text, _seen_ids, affect_weight))

        lines = []
        if user_crystals:
            lines.append(
                "YOUR PERSONAL MEMORIES (from prior sessions with this person — "
                "reference naturally, these are their own words):"
            )
            for c in user_crystals:
                conf = float(c["confidence"]) if c["confidence"] else 0
                text = (c["crystal_text"] or "")[:_USER_SNIPPET]
                lines.append(f"- [{c['domain']}] {text} (confidence: {conf:.2f})")
        if clinical_dna:
            lines.append(
                "CLINICAL DNA (your lived growth lessons — these define "
                "HOW you respond, follow them precisely):"
            )
            for c in clinical_dna:
                conf = float(c["confidence"]) if c["confidence"] else 0
                text = (c["crystal_text"] or "")[:_USER_SNIPPET]
                lines.append(f"- {text} (confidence: {conf:.2f})")
        if global_crystals:
            lines.append(
                "GENERAL KNOWLEDGE (validated therapeutic insights — "
                "reference when relevant):"
            )
            for c in global_crystals:
                conf = float(c["confidence"]) if c["confidence"] else 0
                text = (c["crystal_text"] or "")[:_GLOBAL_SNIPPET]
                lines.append(f"- [{c['domain']}] {text} (confidence: {conf:.2f})")
        if anticipatory_section:
            lines.append(anticipatory_section)
        result = "\n".join(lines)
        # QUANTUM-CRYSTAL-ARCH: Commit 2 — expose which crystals were injected
        # so the bridge chat persist path can attribute the response to them.
        # Scopes always attach when crystals recalled (verifier needs them even
        # if attribution ids are disabled).
        if crystal_ids:
            attributed = _AttributedContext(result)
            if _ENABLE_CRYSTAL_ATTRIBUTION:
                attributed.crystal_ids = list(crystal_ids)[:50]
            # QUANTUM-CRYSTAL-ARCH — Phase 5b: scopes for symbolic verifier isolation
            # asyncpg Records are not dicts — read scope via mapping access.
            _scopes = []
            for c in crystals:
                try:
                    _scopes.append(str(c["scope"] if "scope" in c.keys() else "global"))
                except Exception:
                    _scopes.append(str((c.get("scope") if isinstance(c, dict) else None) or "global"))
            attributed.crystal_scopes = _scopes[:50]
            return attributed
        return result
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


async def _rerank_by_outcome(conn, crystals: list, limit: int) -> list:
    """L3a: re-rank by attributed C_emo outcomes (crystal_outcome_view).

    Blends live confidence with avg_c_emo from prior outcome-linked recalls.
    Clinical/defense crystals are eligible for *ranking* nudges only — this
    path never UPDATEs nate_intelligence_crystals.confidence.
    """
    if not crystals or not _OUTCOME_RECALL_RANK or limit <= 0:
        return list(crystals)[:limit] if limit else list(crystals)
    try:
        ids = [c["id"] for c in crystals if c.get("id") is not None]
        if not ids:
            return list(crystals)[:limit]
        rows = await conn.fetch(
            """
            SELECT crystal_id,
                   AVG(c_emo) FILTER (WHERE c_emo IS NOT NULL) AS avg_c_emo,
                   COUNT(*) FILTER (WHERE c_emo IS NOT NULL) AS n
            FROM crystal_outcome_view
            WHERE crystal_id = ANY($1::int[])
            GROUP BY crystal_id
            HAVING COUNT(*) FILTER (WHERE c_emo IS NOT NULL) >= $2
            """,
            ids,
            max(1, _OUTCOME_RECALL_MIN_SAMPLE),
        )
        by_id = {r["crystal_id"]: r for r in rows}
        if not by_id:
            return list(crystals)[:limit]
        blend = max(0.0, min(1.0, _OUTCOME_RECALL_BLEND))
        scored = []
        for c in crystals:
            conf = float(c["confidence"] if c.get("confidence") is not None else 0.0)
            out = by_id.get(c["id"])
            if out is not None and out["avg_c_emo"] is not None:
                avg = float(out["avg_c_emo"])
                # Map C_emo [0,1] into a rank score; blend with stored confidence.
                blended = conf * (1.0 - blend) + avg * blend
            else:
                blended = conf
            scored.append((blended, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:limit]]
    except Exception as e:
        logger.debug("crystal_recall_bridge: outcome rerank skipped: %s", e)
        return list(crystals)[:limit]


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
            # Note 2c defense-in-depth: even though upstream recall paths
            # already filter awaiting_clinician_authoring crystals, this query
            # accepts raw crystal_ids from any caller. Reapply the filter so
            # engineer-authored placeholders can never enter the co-activation
            # graph (which would taint similarity edges in production).
            rows = await conn.fetch(
                """SELECT id, LEFT(content_hash, 16) as hash_prefix
                   FROM nate_intelligence_crystals
                   WHERE id = ANY($1::int[])
                     AND content_hash IS NOT NULL AND content_hash != ''
                     AND (crystal_status IS NULL OR crystal_status = 'production')""",
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
                     AND (scope = 'user' OR scope LIKE 'user:%')
                     AND (crystal_status IS NULL OR crystal_status = 'production')
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


async def crystallize_coach_observation(
    db_pool,
    coach_hardware_id: str,
    client_hardware_id: str,
    observation_text: str,
    domain: str = "clinical",
    observation_type: str = "coaching_note",
) -> Optional[str]:
    """
    Convert a coach observation into a PROMOTED crystal.
    Coach-sourced crystals get higher confidence (0.85)
    than auto-generated crystals (0.50) because they are
    human-validated clinical insight.
    """
    if not db_pool or not client_hardware_id:
        return None
    text = (observation_text or "").strip()
    if len(text) < 2:
        return None

    crystal_text = f"Coach observation: {text}"
    coach_hw = (coach_hardware_id or "").strip()

    # QUANTUM-CRYSTAL-ARCH — Slice E (Bee HIV+): write-side tenancy check.
    # When ENABLE_PROGRAM_ISOLATION is on, refuse coach observations that cross
    # cohort boundaries (coach in program X writing about client in program Y,
    # or unprogrammed coach writing about a cohort client). BAA §8.7A. Flag-off
    # or program_isolation unavailable = zero behavior change.
    try:
        from app.services.program_isolation import (
            is_enabled as _prog_enabled,
            get_user_program_id as _prog_user,
        )
        if _prog_enabled():
            _coach_pid = await _prog_user(db_pool, coach_hw) if coach_hw else None
            _client_pid = await _prog_user(db_pool, client_hardware_id)
            if _client_pid and _coach_pid != _client_pid:
                logger.warning(
                    "crystallize_coach_observation: REFUSED cross-program write "
                    "(coach_pid=%s client_pid=%s)",
                    _coach_pid or "none", _client_pid,
                )
                return None
    except Exception as _pe:
        logger.debug("crystallize_coach_observation: tenancy check skipped: %s", _pe)

    try:
        async with db_pool.acquire() as conn:
            user_uuid = await conn.fetchval(
                "SELECT id FROM users WHERE hardware_id = $1 OR username = $1 OR id::text = $1 LIMIT 1",
                client_hardware_id,
            )
            if not user_uuid:
                logger.warning(
                    "crystallize_coach_observation: no user for client_hw=%s",
                    client_hardware_id[:16] if client_hardware_id else "",
                )
                return None

            # Scope hash to client + type so identical text for different clients does not collide.
            content_hash = hashlib.sha256(
                f"{user_uuid}|{observation_type}|{crystal_text}".encode()
            ).hexdigest()

            meta = {
                "observation_type": observation_type,
                "coach_hardware_id": coach_hw,
            }
            row = await conn.fetchrow(
                """
                INSERT INTO nate_intelligence_crystals
                    (crystal_text, domain, scope, topics, source_count,
                     generation, confidence, content_hash, user_id, origin_surface, metadata)
                VALUES ($1, $2, 'user', '{}'::text[], 1, 1, 0.85, $3, $4, $5, $6::jsonb)
                ON CONFLICT (content_hash) DO NOTHING
                RETURNING content_hash
                """,
                crystal_text,
                domain,
                content_hash,
                user_uuid,
                "coach_observation",
                json.dumps(meta),
            )

        if not row:
            return None

        logger.info(
            "crystal_bridge: coach observation crystal (surface=coach_observation, type=%s, client=%s)",
            observation_type,
            client_hardware_id[:12],
        )

        try:
            from app.services.vectorize_service import index_wisdom, is_vectorize_configured

            if is_vectorize_configured():
                await index_wisdom(
                    user_id=str(user_uuid),
                    wisdom_id=f"crystal_{content_hash[:16]}",
                    insight_type=f"crystal_{domain}_coach",
                    content=crystal_text,
                    source="coach_observation",
                    domain=domain,
                )
        except Exception as _vec_err:
            logger.debug("crystal_bridge: coach observation vectorize failed (non-fatal): %s", _vec_err)

        ch = row.get("content_hash")
        if ch:
            try:
                from app.services.wisdom_lifecycle_manager import WisdomLifecycleManager

                async def _coach_observation_wisdom() -> None:
                    try:
                        mgr = WisdomLifecycleManager(db_pool, None)
                        await mgr.extract_wisdom(
                            "coaching",
                            text,
                            user_id=str(user_uuid) if user_uuid else None,
                            domain=domain,
                            confidence=0.85,
                        )
                    except Exception as _w_err:
                        logger.debug(
                            "crystal_bridge: coach observation wisdom extract (non-fatal): %s",
                            _w_err,
                        )

                try:
                    asyncio.get_running_loop().create_task(_coach_observation_wisdom())
                except RuntimeError:
                    logger.debug(
                        "crystallize_coach_observation: no running loop for wisdom extract",
                    )
            except Exception as _wl_err:
                logger.debug(
                    "crystal_bridge: coach observation wisdom schedule failed (non-fatal): %s",
                    _wl_err,
                )

        # QUANTUM-CRYSTAL-ARCH — Dual-COO coach-label feedback (YELLOW/RED)
        try:
            from app.websocket.cli_dual_coo import (
                RISK_RED,
                RISK_YELLOW,
                enqueue_ceo,
                classify_risk,
            )

            _corr = (
                "incorrect" in text.lower()
                or "do not" in text.lower()
                or "nate was" in text.lower()
                or observation_type in ("coach_override", "correction")
            )
            if _corr:
                _risk = classify_risk(
                    kind="coach_label", domain=domain, notes=text[:200],
                )
                if _risk not in (RISK_YELLOW, RISK_RED):
                    _risk = RISK_YELLOW if domain != "clinical" else RISK_RED
                enqueue_ceo(
                    risk=_risk,
                    title=f"Coach label ({observation_type})",
                    detail=text[:500],
                    origin="cloud",
                    task_id=f"coach_label:{(ch or content_hash)[:24]}",
                    payload={
                        "client": (client_hardware_id or "")[:80],
                        "coach": coach_hw[:80],
                        "domain": domain,
                        "content_hash": (ch or "")[:64] if ch else "",
                    },
                    dedup_ttl_s=86400,
                )
        except Exception as _ceo_err:
            logger.debug("coach_label ceo route: %s", _ceo_err)

        return row["content_hash"]
    except Exception as e:
        logger.warning("crystallize_coach_observation: %s", e)
        return None


async def crystallize_wisdom_absorption(
    db_pool,
    user_ref: str,
    crystal_text: str,
    domain: str = "clinical",
    extraction_id: str = "",
    absorption_source: str = "wisdom_absorption",
) -> Optional[str]:
    """
    Promote an absorbed wisdom extraction into nate_intelligence_crystals
    (high confidence, dedicated origin_surface). Does not alter conversation heuristics.
    """
    if not db_pool or not (crystal_text or "").strip():
        return None
    text = (crystal_text or "").strip()
    ext = (extraction_id or "").strip()
    src = (absorption_source or "wisdom")[:120]

    try:
        async with db_pool.acquire() as conn:
            user_uuid = None
            ur = (user_ref or "").strip()
            if ur:
                user_uuid = await conn.fetchval(
                    "SELECT id FROM users WHERE hardware_id = $1 OR username = $1 OR id::text = $1 LIMIT 1",
                    ur,
                )

            # QUANTUM-CRYSTAL-ARCH: fail CLOSED on unresolved user. Wisdom
            # extractions come from user conversations; if user_ref is empty
            # or doesn't resolve, writing scope='global' leaks that client's
            # disclosure into the global recall pool (2026-07 public-trial
            # F4c confidentiality breach — crystals 630869/630952/637972/
            # 637973). Skip crystal creation entirely rather than default
            # to global. Deliberately-global absorption must go through a
            # separate, explicit path — never this fallback.
            if not user_uuid:
                logger.warning(
                    "crystal_bridge: wisdom absorption SKIPPED — user_ref %r "
                    "unresolved (extraction_id=%s); refusing global fallback",
                    ur[:40], ext[:16] if ext else "",
                )
                return None

            if user_uuid:
                content_hash = hashlib.sha256(
                    f"{user_uuid}|wisdom_absorption|{ext}|{text}".encode()
                ).hexdigest()
            else:
                content_hash = hashlib.sha256(
                    f"global|wisdom_absorption|{ext}|{text}".encode()
                ).hexdigest()

            scope = "user" if user_uuid else "global"
            meta = {
                "absorption_source": src,
                "wisdom_extraction_id": ext,
            }
            row = await conn.fetchrow(
                """
                INSERT INTO nate_intelligence_crystals
                    (crystal_text, domain, scope, topics, source_count,
                     generation, confidence, content_hash, user_id, origin_surface, metadata)
                VALUES ($1, $2, $3, '{}'::text[], 1, 1, 0.92, $4, $5, $6, $7::jsonb)
                ON CONFLICT (content_hash) DO NOTHING
                RETURNING content_hash
                """,
                text,
                domain[:50] if domain else "clinical",
                scope,
                content_hash,
                user_uuid,
                "wisdom_absorption",
                json.dumps(meta),
            )

        if not row:
            return None

        logger.info(
            "crystal_bridge: wisdom absorption crystal (extraction_id=%s, scope=%s)",
            ext[:16] if ext else "",
            scope,
        )

        try:
            from app.services.vectorize_service import index_wisdom, is_vectorize_configured

            if is_vectorize_configured():
                await index_wisdom(
                    user_id=str(user_uuid) if user_uuid else "nate_crystal",
                    wisdom_id=f"crystal_{content_hash[:16]}",
                    insight_type=f"crystal_{domain}_wisdom_absorption",
                    content=text,
                    source="wisdom_absorption",
                    domain=domain,
                )
        except Exception as _vec_err:
            logger.debug("crystal_bridge: wisdom absorption vectorize failed (non-fatal): %s", _vec_err)

        return row["content_hash"]
    except Exception as e:
        logger.warning("crystallize_wisdom_absorption: %s", e)
        return None


async def crystallize_from_conversation(
    db_pool,
    hardware_id: str,
    user_text: str,
    nate_response: str,
    user_name: str = "",
    domain: str = "clinical",
    min_score: int = _MIN_SCORE,
    origin_surface: str = "bridge_chat",
) -> Optional[str]:
    """
    Extract a user-scoped crystal from a conversation turn when the
    exchange contains enough therapeutic signal.

    Heuristic-only (no LLM call) so it adds zero latency.
    Low initial confidence (0.50) — the backend crystallizer can
    validate and promote later.  Deduplication via content_hash.

    Returns content_hash when a new row is inserted, else None.
    """
    if not db_pool or not hardware_id:
        return None
    # QUANTUM-CRYSTAL-ARCH — Tier-1 D.14b: never forge crystals from battery turns
    try:
        from app.services.six_quotient_battery_quarantine import should_block_crystallize

        if should_block_crystallize(
            origin_surface=origin_surface or "",
            user_text=user_text or "",
            nate_response=nate_response or "",
        ):
            return None
    except Exception:
        pass
    is_voice = origin_surface == "voice_call"
    effective_min_len = _MIN_USER_LEN_VOICE if is_voice else _MIN_USER_LEN
    if len(user_text) < effective_min_len:
        return None

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
        return None

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

    # QUANTUM-CRYSTAL-ARCH: Tier 4 — optional IFS parts-activity metadata
    # (flag-gated; None preserves the pre-existing NULL metadata behavior)
    _ifs_meta = None
    if (_os.getenv("BRIDGE_IFS_METADATA", "") or "").strip().lower() in ("1", "true", "yes", "on"):
        try:
            from .bridge_enrichment import ifs_part_hints as _ifs_hints
            _parts = _ifs_hints(user_text)
            if _parts:
                _ifs_meta = json.dumps({"ifs_parts": _parts})
        except Exception:
            _ifs_meta = None

    try:
        async with db_pool.acquire() as conn:
            user_uuid = await conn.fetchval(
                "SELECT id FROM users WHERE hardware_id = $1 OR username = $1 OR id::text = $1 LIMIT 1",
                hardware_id,
            )

            # QUANTUM-CRYSTAL-ARCH: fail CLOSED on unresolved user. This
            # function always writes scope='user' — if hardware_id doesn't
            # resolve, user_id would be NULL while scope stays 'user',
            # producing an orphaned user-scoped crystal with no owner.
            # The 2026-07-09 incident found exactly this pattern (a
            # scope='user:<id>' crystal with user_id IS NULL). Recall now
            # allowlists scope='global' only, so an orphan like this can
            # no longer leak into the global pool — but it also can never
            # be recalled by its rightful owner, so it's just a personal
            # disclosure sitting unscoped in the DB. Refuse the write.
            if not user_uuid:
                logger.warning(
                    "crystal_bridge: conversation crystal SKIPPED — hardware_id %r "
                    "unresolved; refusing to write orphaned user-scoped crystal",
                    (hardware_id or "")[:40],
                )
                return None

            ins_row = await conn.fetchrow(
                """
                INSERT INTO nate_intelligence_crystals
                    (crystal_text, domain, scope, topics, source_count,
                     generation, confidence, content_hash, user_id, origin_surface, metadata)
                VALUES ($1, $2, 'user', '{}'::text[], 1, 0, 0.50, $3, $4, $5, $6::jsonb)
                ON CONFLICT (content_hash) DO NOTHING
                RETURNING confidence
                """,
                crystal_text, matched_domain, content_hash, user_uuid, origin_surface, _ifs_meta,
            )

        if not ins_row:
            return None

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

        try:
            conf = float(ins_row["confidence"])
            if conf >= 0.5 and origin_surface != "classroom_video":
                from app.services.wisdom_lifecycle_manager import (
                    schedule_wisdom_extraction_after_conversation,
                )

                schedule_wisdom_extraction_after_conversation(
                    db_pool,
                    hardware_id,
                    crystal_text,
                    str(user_uuid) if user_uuid else None,
                    matched_domain,
                    origin_surface,
                    conf,
                )
        except Exception as _wl_err:
            logger.debug("crystal_bridge: wisdom lifecycle extract (non-fatal): %s", _wl_err)
        # QUANTUM-CRYSTAL-ARCH — stamp crystal with latest PGSD coords (non-blocking)
        try:
            async with db_pool.acquire() as _conn_pgsd:
                _snap = await _conn_pgsd.fetchrow(
                    """
                    SELECT id, d1_valence, d2_arousal, d3_relational,
                           d4_temporal_depth, d5_integration,
                           emotional_fingerprint, coherence
                    FROM pgsd_snapshots
                    WHERE user_id = $1 OR username = $1
                    ORDER BY computed_at DESC LIMIT 1
                    """,
                    hardware_id,
                )
                if _snap:
                    await _conn_pgsd.execute(
                        """
                        UPDATE nate_intelligence_crystals SET
                            pgsd_d1 = $2, pgsd_d2 = $3, pgsd_d3 = $4,
                            pgsd_d4 = $5, pgsd_d5 = $6,
                            pgsd_fingerprint = $7, pgsd_coherence = $8,
                            pgsd_snapshot_id = $9
                        WHERE content_hash = $1
                        """,
                        content_hash,
                        _snap["d1_valence"],
                        _snap["d2_arousal"],
                        _snap["d3_relational"],
                        _snap["d4_temporal_depth"],
                        _snap["d5_integration"],
                        _snap["emotional_fingerprint"],
                        _snap["coherence"],
                        _snap["id"],
                    )
        except Exception:
            pass
        # QUANTUM-CRYSTAL-ARCH — PGSD auto-snapshot after successful crystallize
        try:
            from app.services.pgsd_triggers import notify_user

            # Default bridge_chat so therapy domain surface_hits score without backfill
            _src = (origin_surface or "bridge_chat").strip() or "bridge_chat"
            notify_user(hardware_id, source=_src)
        except Exception:
            pass
        return content_hash
    except Exception as e:
        logger.warning("crystallize_from_conversation: %s", e)
        return None


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

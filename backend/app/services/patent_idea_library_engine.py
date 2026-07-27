"""Dual-COO patent idea library — score, renew, promote (≥90), archive, weight adapt.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("patent_idea_library_engine")

CATEGORIES = ("world_qol", "platform", "qec_quantum", "queens_nate")
CATEGORY_MIX = (
    ("world_qol", 0.30),
    ("platform", 0.25),
    ("qec_quantum", 0.25),
    ("queens_nate", 0.20),
)

SEED_WEIGHTS = {
    "novelty": 0.12,
    "claim_clarity": 0.12,
    "code_alignment": 0.12,
    "commercial_fit": 0.08,
    "prior_art_safety": 0.10,
    "portfolio_gap": 0.08,
    "world_qol_impact": 0.10,
    "platform_leverage": 0.10,
    "qec_depth": 0.10,
    "queens_nate_lift": 0.08,
    "proven_possibility": 0.10,
}

DIM_KEYS = tuple(SEED_WEIGHTS.keys())

PROMOTE_MIN = float(os.getenv("PATENT_IDEA_PROMOTE_MIN", "90"))
EXPLORE_LO = 75.0
EXPLORE_HI = PROMOTE_MIN
STUDY_MAX_PER_DAY = int(os.getenv("PATENT_IDEA_STUDY_MAX_PER_DAY", "3"))
RENEW_MAX_PER_DAY = int(os.getenv("PATENT_IDEA_RENEW_MAX_PER_DAY", "10"))
ARCHIVE_MAX_PER_DAY = int(os.getenv("PATENT_IDEA_ARCHIVE_MAX_PER_DAY", "20"))
PROMOTE_EXPLOIT_K = 4
PROMOTE_EXPLORE_K = 1
UCB_C = 12.0
DIVERSITY_JACCARD = 0.65
WEIGHT_ETA = 0.02
WEIGHT_MIN = 0.05
WEIGHT_MAX = 0.40


def patent_reflections_enabled() -> bool:
    return os.getenv("ENABLE_PATENT_REFLECTIONS", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return (s or "idea")[:80]


def dedupe_hash(title: str, paths: Sequence[str]) -> str:
    raw = f"{(title or '').strip().lower()}|{'|'.join(sorted(paths or []))}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def jaccard_tokens(a: str, b: str) -> float:
    ta = set(re.findall(r"[a-z0-9]{3,}", (a or "").lower()))
    tb = set(re.findall(r"[a-z0-9]{3,}", (b or "").lower()))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(1, len(ta | tb))


def path_jaccard(a: Sequence[str], b: Sequence[str]) -> float:
    sa, sb = set(a or []), set(b or [])
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / max(1, len(sa | sb))


def clamp_weights(weights: Dict[str, float]) -> Dict[str, float]:
    out = {}
    for k in DIM_KEYS:
        out[k] = max(WEIGHT_MIN, min(WEIGHT_MAX, float(weights.get(k, SEED_WEIGHTS[k]))))
    total = sum(out.values()) or 1.0
    return {k: round(v / total, 6) for k, v in out.items()}


def compute_rank_score(dims: Dict[str, float], weights: Dict[str, float]) -> float:
    w = clamp_weights(weights)
    score = 0.0
    for k in DIM_KEYS:
        d = max(0.0, min(100.0, float(dims.get(k, 0.0))))
        score += w[k] * d
    return round(score, 2)


def ucb_score(rank: float, renewals: int, n_pool: int) -> float:
    return float(rank) + UCB_C * math.sqrt(math.log(max(n_pool, 1) + 1) / (max(renewals, 0) + 1))


def pick_study_category(rng_roll: float) -> str:
    """rng_roll in [0,1)."""
    acc = 0.0
    for cat, p in CATEGORY_MIX:
        acc += p
        if rng_roll < acc:
            return cat
    return "platform"


class PatentIdeaLibraryEngine:
    def __init__(self, db_pool, *, patent_root: Optional[str] = None):
        self.db_pool = db_pool
        root = patent_root or os.getenv(
            "PATENT_CORPUS_ROOT",
            os.path.join(os.getcwd(), "patent"),
        )
        self.patent_root = os.path.abspath(root)
        self.sandbox_root = os.path.join(self.patent_root, "sandbox_reflections")
        self.archive_root = os.path.join(self.sandbox_root, "archive")

    def _assert_sandbox_path(self, path: str) -> str:
        abs_p = os.path.abspath(path)
        sandbox = os.path.abspath(self.sandbox_root)
        if not abs_p.startswith(sandbox + os.sep) and abs_p != sandbox:
            raise ValueError(f"path outside sandbox: {path}")
        # Never allow writing official claim files
        if "/QUANTUM_" in abs_p or "/PATENT_" in abs_p:
            if "sandbox_reflections" not in abs_p:
                raise ValueError("refusing official patent path")
        return abs_p

    async def get_weights(self) -> Dict[str, float]:
        if not self.db_pool:
            return dict(SEED_WEIGHTS)
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT weights FROM patent_rank_weight_state WHERE id = 1"
            )
        if not row:
            return dict(SEED_WEIGHTS)
        raw = row["weights"]
        if isinstance(raw, str):
            raw = json.loads(raw)
        return clamp_weights({k: float((raw or {}).get(k, SEED_WEIGHTS[k])) for k in DIM_KEYS})

    async def count_new_ideas_today(self) -> int:
        if not self.db_pool:
            return STUDY_MAX_PER_DAY
        async with self.db_pool.acquire() as conn:
            n = await conn.fetchval(
                """
                SELECT COUNT(*) FROM patent_idea_library
                WHERE created_at >= date_trunc('day', NOW() AT TIME ZONE 'UTC')
                  AND parent_id IS NULL
                """
            )
        return int(n or 0)

    async def study_cap_remaining(self) -> int:
        return max(0, STUDY_MAX_PER_DAY - await self.count_new_ideas_today())

    async def list_library(
        self,
        *,
        status: Optional[str] = None,
        category: Optional[str] = None,
        topic: Optional[str] = None,
        sort: str = "rank",
        limit: int = 100,
        include_archived: bool = False,
    ) -> List[Dict[str, Any]]:
        if not self.db_pool:
            return []
        clauses = ["1=1"]
        args: List[Any] = []
        if status:
            args.append(status)
            clauses.append(f"library_status = ${len(args)}")
        elif not include_archived:
            clauses.append("library_status <> 'archived'")
        if category:
            args.append(category)
            clauses.append(f"primary_category = ${len(args)}")
        if topic:
            args.append(topic)
            clauses.append(f"${len(args)} = ANY(topics)")
        order = "rank_score DESC, updated_at DESC"
        if sort == "ucb":
            order = "rank_score DESC, renewal_count ASC, updated_at DESC"
        elif sort == "category":
            order = "primary_category, rank_score DESC"
        args.append(max(1, min(limit, 500)))
        sql = f"""
            SELECT * FROM patent_idea_library
            WHERE {' AND '.join(clauses)}
            ORDER BY {order}
            LIMIT ${len(args)}
        """
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
        out = []
        for r in rows:
            d = dict(r)
            for k, v in list(d.items()):
                if hasattr(v, "isoformat"):
                    d[k] = v.isoformat()
                elif isinstance(v, (list, dict)):
                    pass
                else:
                    try:
                        if hasattr(v, "__float__") and not isinstance(v, bool):
                            d[k] = float(v) if k in ("rank_score", "uncertainty") else v
                    except Exception:
                        pass
            if isinstance(d.get("rank_dimensions"), str):
                try:
                    d["rank_dimensions"] = json.loads(d["rank_dimensions"])
                except Exception:
                    pass
            out.append(d)
        return out

    def group_by_category(
        self, rows: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
        """category -> topic -> ideas."""
        grouped: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
            c: {} for c in CATEGORIES
        }
        for row in rows:
            cat = row.get("primary_category") or "platform"
            if cat not in grouped:
                grouped[cat] = {}
            topics = row.get("topics") or ["general"]
            if not topics:
                topics = ["general"]
            for t in topics:
                grouped[cat].setdefault(t, []).append(row)
        return grouped

    def heuristic_dimensions(
        self,
        *,
        category: str,
        summary: str,
        paths: Sequence[str],
        critique_hits: int = 0,
        has_proven_anchor: bool = False,
        claim_map_hits: int = 0,
        prior_art_hits: int = 0,
    ) -> Dict[str, float]:
        text = f"{summary} {' '.join(paths)}".lower()
        base = {k: 55.0 for k in DIM_KEYS}
        # Category mission boosts
        if category == "world_qol":
            base["world_qol_impact"] = 78.0
        elif category == "platform":
            base["platform_leverage"] = 78.0
        elif category == "qec_quantum":
            base["qec_depth"] = 80.0
        elif category == "queens_nate":
            base["queens_nate_lift"] = 80.0

        if any(x in text for x in ("c_emo", "nevedal", "odpe", "coherence", "qec")):
            base["qec_depth"] = max(base["qec_depth"], 72.0)
            base["proven_possibility"] = max(base["proven_possibility"], 70.0)
        if any(x in text for x in ("queen", "dual-coo", "dual_coo", "little nate", "nate")):
            base["queens_nate_lift"] = max(base["queens_nate_lift"], 70.0)
        if any(x in text for x in ("trust", "auditor", "bridge", "sanctuary", "platform")):
            base["platform_leverage"] = max(base["platform_leverage"], 68.0)
        if any(x in text for x in ("quality of life", "trauma", "wellbeing", "community")):
            base["world_qol_impact"] = max(base["world_qol_impact"], 70.0)

        base["code_alignment"] = min(95.0, 50.0 + 8.0 * min(claim_map_hits, 5))
        base["portfolio_gap"] = 65.0 if claim_map_hits < 2 else 45.0
        base["prior_art_safety"] = max(20.0, 85.0 - 12.0 * min(prior_art_hits, 5))
        base["novelty"] = 70.0 if len(summary) > 120 else 55.0
        base["claim_clarity"] = 68.0 if len(summary) > 80 else 50.0
        base["commercial_fit"] = 60.0
        if has_proven_anchor:
            base["proven_possibility"] = max(base["proven_possibility"], 85.0)
        else:
            base["proven_possibility"] = min(base["proven_possibility"], 40.0)

        if critique_hits >= 2:
            base["novelty"] = max(0.0, base["novelty"] - 10.0)
            base["prior_art_safety"] = max(0.0, base["prior_art_safety"] - 10.0)
            base["proven_possibility"] = max(0.0, base["proven_possibility"] - 10.0)
        return {k: round(float(base[k]), 2) for k in DIM_KEYS}

    async def upsert_from_study(
        self,
        *,
        title: str,
        category: str,
        topics: Sequence[str],
        summary: str,
        reflection_md: str,
        source_paths: Sequence[str],
        critique_md: str = "",
        critique_hits: int = 0,
        has_proven_anchor: bool = False,
        parent_id: Optional[int] = None,
        force_new: bool = False,
    ) -> Dict[str, Any]:
        if category not in CATEGORIES:
            raise ValueError(f"invalid category: {category}")
        if not self.db_pool:
            return {"status": "error", "error": "no_db"}

        if parent_id is None and not force_new:
            remaining = await self.study_cap_remaining()
            if remaining <= 0:
                return {"status": "skipped", "reason": "study_cap", "cap": STUDY_MAX_PER_DAY}

        weights = await self.get_weights()
        claim_hits, prior_hits = await self._signal_counts(source_paths)
        dims = self.heuristic_dimensions(
            category=category,
            summary=summary,
            paths=source_paths,
            critique_hits=critique_hits,
            has_proven_anchor=has_proven_anchor,
            claim_map_hits=claim_hits,
            prior_art_hits=prior_hits,
        )
        score = compute_rank_score(dims, weights)
        slug_base = slugify(title)
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        slug = f"{day}-{slug_base}"
        dhash = dedupe_hash(title, source_paths)

        os.makedirs(self.sandbox_root, exist_ok=True)
        rel = f"{day}_{slug_base}.md"
        sandbox_path = self._assert_sandbox_path(os.path.join(self.sandbox_root, rel))
        header = (
            f"# {title}\n\n"
            f"- category: `{category}`\n"
            f"- topics: {', '.join(topics or [])}\n"
            f"- sources: {', '.join(source_paths or [])}\n"
            f"- rank_score: {score}\n\n"
            f"## Summary\n\n{summary}\n\n"
            f"## Reflection\n\n{reflection_md}\n\n"
            f"## Critique\n\n{critique_md or '_none_'}\n"
        )
        with open(sandbox_path, "w", encoding="utf-8") as f:
            f.write(header)

        async with self.db_pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT id FROM patent_idea_library WHERE dedupe_hash = $1 AND library_status = 'active'",
                dhash,
            )
            if existing and parent_id is None:
                lib_id = int(existing["id"])
                await conn.execute(
                    """
                    UPDATE patent_idea_library SET
                        title = $2, idea_summary = $3, latest_reflection_md = $4,
                        sandbox_path = $5, rank_score = $6, rank_dimensions = $7::jsonb,
                        critique_md = $8, last_scored_at = NOW(),
                        renewal_count = renewal_count + 1,
                        next_renew_at = NOW() + INTERVAL '14 days',
                        updated_at = NOW()
                    WHERE id = $1
                    """,
                    lib_id, title[:300], summary[:4000], reflection_md[:20000],
                    sandbox_path, score, json.dumps(dims), (critique_md or "")[:8000],
                )
                reason = "renew"
            else:
                # uniquify slug
                n = 0
                candidate = slug
                while await conn.fetchval(
                    "SELECT 1 FROM patent_idea_library WHERE slug = $1", candidate
                ):
                    n += 1
                    candidate = f"{slug}-{n}"
                lib_id = await conn.fetchval(
                    """
                    INSERT INTO patent_idea_library (
                        slug, title, primary_category, topics, source_patent_paths,
                        idea_summary, latest_reflection_md, sandbox_path,
                        rank_score, rank_dimensions, library_status, parent_id,
                        critique_md, dedupe_hash, last_scored_at, next_renew_at,
                        proposed_by
                    ) VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,'active',$11,$12,$13,
                        NOW(), NOW() + INTERVAL '14 days', 'dual_coo'
                    ) RETURNING id
                    """,
                    candidate, title[:300], category, list(topics or []),
                    list(source_paths or []), summary[:4000], reflection_md[:20000],
                    sandbox_path, score, json.dumps(dims), parent_id,
                    (critique_md or "")[:8000], dhash,
                )
                reason = "initial"

            await conn.execute(
                """
                INSERT INTO patent_idea_rank_history
                    (library_id, rank_score, rank_dimensions, weight_snapshot, critique_applied, reason)
                VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, $6)
                """,
                lib_id, score, json.dumps(dims), json.dumps(weights),
                critique_hits >= 2, reason,
            )

        return {
            "status": "ok",
            "library_id": int(lib_id),
            "rank_score": score,
            "dimensions": dims,
            "sandbox_path": sandbox_path,
            "reason": reason,
        }

    async def _signal_counts(self, paths: Sequence[str]) -> Tuple[int, int]:
        if not self.db_pool:
            return 0, 0
        claim_hits = 0
        prior_hits = 0
        try:
            async with self.db_pool.acquire() as conn:
                claim_hits = int(await conn.fetchval(
                    "SELECT COUNT(*) FROM patent_claim_map"
                ) or 0)
                prior_hits = int(await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM prior_art_sweep_log
                    WHERE created_at > NOW() - INTERVAL '30 days'
                    """
                ) or 0)
        except Exception as e:
            logger.debug("signal counts: %s", e)
        # Soft signal from paths length
        claim_hits = min(5, max(0, claim_hits // 50) + (1 if paths else 0))
        prior_hits = min(5, prior_hits // 10)
        return claim_hits, prior_hits

    async def rescore_idea(self, library_id: int, *, reason: str = "renew") -> Dict[str, Any]:
        if not self.db_pool:
            return {"status": "error", "error": "no_db"}
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM patent_idea_library WHERE id = $1", library_id
            )
        if not row:
            return {"status": "error", "error": "not_found"}
        if row["library_status"] == "archived":
            return {"status": "skipped", "reason": "archived"}
        weights = await self.get_weights()
        claim_hits, prior_hits = await self._signal_counts(row["source_patent_paths"] or [])
        critique = row["critique_md"] or ""
        critique_hits = len(re.findall(r"(?m)^\s*[-*]\s+", critique))
        dims = self.heuristic_dimensions(
            category=row["primary_category"],
            summary=row["idea_summary"] or "",
            paths=row["source_patent_paths"] or [],
            critique_hits=min(3, critique_hits),
            has_proven_anchor=bool(row["source_patent_paths"]),
            claim_map_hits=claim_hits,
            prior_art_hits=prior_hits,
        )
        score = compute_rank_score(dims, weights)
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE patent_idea_library SET
                    rank_score = $2, rank_dimensions = $3::jsonb,
                    last_scored_at = NOW(), renewal_count = renewal_count + 1,
                    next_renew_at = NOW() + INTERVAL '14 days', updated_at = NOW()
                WHERE id = $1
                """,
                library_id, score, json.dumps(dims),
            )
            await conn.execute(
                """
                INSERT INTO patent_idea_rank_history
                    (library_id, rank_score, rank_dimensions, weight_snapshot, critique_applied, reason)
                VALUES ($1,$2,$3::jsonb,$4::jsonb,$5,$6)
                """,
                library_id, score, json.dumps(dims), json.dumps(weights),
                critique_hits >= 2, reason[:32],
            )
        return {"status": "ok", "library_id": library_id, "rank_score": score, "dimensions": dims}

    async def renew_stale(self, *, limit: int = 10) -> Dict[str, Any]:
        if not self.db_pool:
            return {"status": "ok", "renewed": 0}
        limit = max(1, min(limit, RENEW_MAX_PER_DAY))
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id FROM patent_idea_library
                WHERE library_status = 'active'
                  AND (next_renew_at IS NULL OR next_renew_at <= NOW()
                       OR last_scored_at IS NULL
                       OR last_scored_at < NOW() - INTERVAL '14 days')
                ORDER BY COALESCE(next_renew_at, '1970-01-01'::timestamptz) ASC
                LIMIT $1
                """,
                limit,
            )
        renewed = []
        for r in rows:
            res = await self.rescore_idea(int(r["id"]), reason="renew")
            if res.get("status") == "ok":
                renewed.append(res)
        return {"status": "ok", "renewed": len(renewed), "items": renewed}

    def diversity_filter(
        self,
        candidates: List[Dict[str, Any]],
        recent: List[Dict[str, Any]],
        *,
        max_per_category: int = 2,
    ) -> List[Dict[str, Any]]:
        kept: List[Dict[str, Any]] = []
        cat_counts: Dict[str, int] = {}
        for c in candidates:
            cat = c.get("primary_category") or "platform"
            if cat_counts.get(cat, 0) >= max_per_category:
                continue
            too_close = False
            for other in list(recent) + kept:
                pj = path_jaccard(
                    c.get("source_patent_paths") or [],
                    other.get("source_patent_paths") or [],
                )
                tj = jaccard_tokens(
                    c.get("idea_summary") or "",
                    other.get("idea_summary") or "",
                )
                if max(pj, tj) > DIVERSITY_JACCARD:
                    too_close = True
                    break
            if too_close:
                continue
            kept.append(c)
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
        return kept

    async def promote_batch(self) -> Dict[str, Any]:
        """Exploit Top-K (≥90) + 1 explore [75,90). Creates reflections via reflection engine."""
        if not self.db_pool:
            return {"status": "ok", "promoted": []}
        from app.services.patent_reflection_engine import PatentReflectionEngine

        async with self.db_pool.acquire() as conn:
            today_n = int(await conn.fetchval(
                """
                SELECT COUNT(*) FROM patent_reflections
                WHERE created_at >= date_trunc('day', NOW() AT TIME ZONE 'UTC')
                """
            ) or 0)
            recent = await conn.fetch(
                """
                SELECT l.source_patent_paths, l.idea_summary, l.primary_category
                FROM patent_idea_library l
                WHERE l.library_status = 'promoted'
                  AND l.updated_at > NOW() - INTERVAL '7 days'
                """
            )
            active = await conn.fetch(
                """
                SELECT * FROM patent_idea_library
                WHERE library_status = 'active'
                ORDER BY rank_score DESC
                LIMIT 200
                """
            )
        recent_d = [dict(r) for r in recent]
        active_d = [dict(r) for r in active]
        for a in active_d:
            if isinstance(a.get("rank_dimensions"), str):
                try:
                    a["rank_dimensions"] = json.loads(a["rank_dimensions"])
                except Exception:
                    a["rank_dimensions"] = {}

        remaining = max(0, (PROMOTE_EXPLOIT_K + PROMOTE_EXPLORE_K) - today_n)
        if remaining <= 0:
            return {"status": "ok", "promoted": [], "reason": "daily_cap"}

        exploit_pool = [
            a for a in active_d if float(a.get("rank_score") or 0) >= PROMOTE_MIN
        ]
        exploit_pool.sort(key=lambda x: float(x.get("rank_score") or 0), reverse=True)
        exploit = self.diversity_filter(exploit_pool, recent_d)[: min(PROMOTE_EXPLOIT_K, remaining)]

        promoted_ids = {int(x["id"]) for x in exploit}
        explore_pick = None
        if remaining > len(exploit):
            explore_pool = [
                a for a in active_d
                if EXPLORE_LO <= float(a.get("rank_score") or 0) < EXPLORE_HI
                and int(a["id"]) not in promoted_ids
            ]
            n_pool = max(len(active_d), 1)
            explore_pool.sort(
                key=lambda x: ucb_score(
                    float(x.get("rank_score") or 0),
                    int(x.get("renewal_count") or 0),
                    n_pool,
                ),
                reverse=True,
            )
            filtered = self.diversity_filter(explore_pool, recent_d + exploit, max_per_category=2)
            if filtered:
                explore_pick = filtered[0]

        refl = PatentReflectionEngine(self.db_pool, library_engine=self)
        results = []
        for row in exploit:
            r = await refl.promote_from_library(int(row["id"]), promote_reason="exploit")
            results.append(r)
        if explore_pick:
            r = await refl.promote_from_library(int(explore_pick["id"]), promote_reason="explore")
            results.append(r)
        return {
            "status": "ok",
            "promoted": results,
            "exploit": len(exploit),
            "explore": 1 if explore_pick else 0,
        }

    async def archive_idea(
        self,
        library_id: int,
        *,
        reason: str = "",
        by: str = "ceo",
    ) -> Dict[str, Any]:
        if not self.db_pool:
            return {"status": "error", "error": "no_db"}
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM patent_idea_library WHERE id = $1", library_id
            )
            if not row:
                return {"status": "error", "error": "not_found"}
            if row["library_status"] == "archived":
                return {"status": "ok", "already": True}
            pre = row["library_status"]
            cat = row["primary_category"] or "platform"
            # Move sandbox file if present
            sp = row["sandbox_path"]
            new_path = sp
            if sp and os.path.isfile(sp):
                dest_dir = os.path.join(self.archive_root, cat)
                os.makedirs(dest_dir, exist_ok=True)
                dest = os.path.join(dest_dir, os.path.basename(sp))
                try:
                    os.replace(sp, dest)
                    new_path = dest
                except Exception as e:
                    logger.warning("archive move failed: %s", e)
            await conn.execute(
                """
                UPDATE patent_idea_library SET
                    library_status = 'archived',
                    pre_archive_status = $2,
                    archived_at = NOW(),
                    archived_by = $3,
                    archive_reason = $4,
                    sandbox_path = COALESCE($5, sandbox_path),
                    updated_at = NOW()
                WHERE id = $1
                """,
                library_id, pre, by[:32], (reason or "")[:1000], new_path,
            )
            await conn.execute(
                """
                UPDATE patent_reflections SET
                    status = 'held',
                    updated_at = NOW()
                WHERE library_id = $1
                  AND status IN ('pending', 'inquiring', 'ready_for_decision')
                """,
                library_id,
            )
        return {"status": "ok", "library_id": library_id, "archived": True}

    async def unarchive_idea(self, library_id: int) -> Dict[str, Any]:
        if not self.db_pool:
            return {"status": "error", "error": "no_db"}
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM patent_idea_library WHERE id = $1", library_id
            )
            if not row:
                return {"status": "error", "error": "not_found"}
            if row["library_status"] != "archived":
                return {"status": "ok", "already_active": True}
            restore = row["pre_archive_status"] or "active"
            if restore not in ("active", "shelved", "promoted"):
                restore = "active"
            await conn.execute(
                """
                UPDATE patent_idea_library SET
                    library_status = $2,
                    archived_at = NULL,
                    archived_by = NULL,
                    archive_reason = NULL,
                    pre_archive_status = NULL,
                    updated_at = NOW()
                WHERE id = $1
                """,
                library_id, restore,
            )
        return {"status": "ok", "library_id": library_id, "status_restored": restore}

    async def auto_archive_stale(self) -> Dict[str, Any]:
        if not self.db_pool:
            return {"status": "ok", "archived": 0}
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id FROM patent_idea_library
                WHERE library_status = 'shelved'
                  AND updated_at < NOW() - INTERVAL '90 days'
                UNION
                SELECT id FROM patent_idea_library
                WHERE library_status = 'active'
                  AND rank_score < 40
                  AND (last_scored_at IS NULL OR last_scored_at < NOW() - INTERVAL '60 days')
                LIMIT $1
                """,
                ARCHIVE_MAX_PER_DAY,
            )
        n = 0
        for r in rows:
            res = await self.archive_idea(
                int(r["id"]), reason="auto_stale", by="dual_coo_auto"
            )
            if res.get("archived"):
                n += 1
        # Superseded parents
        async with self.db_pool.acquire() as conn:
            parents = await conn.fetch(
                """
                SELECT p.id
                FROM patent_idea_library p
                JOIN patent_idea_library c ON c.parent_id = p.id
                WHERE p.library_status = 'active'
                  AND c.library_status = 'active'
                  AND c.rank_score >= p.rank_score + 15
                  AND c.updated_at < NOW() - INTERVAL '30 days'
                LIMIT $1
                """,
                max(0, ARCHIVE_MAX_PER_DAY - n),
            )
        for r in parents:
            res = await self.archive_idea(
                int(r["id"]), reason="superseded_by_child", by="dual_coo_auto"
            )
            if res.get("archived"):
                n += 1
        return {"status": "ok", "archived": n}

    async def adapt_weights(
        self,
        *,
        decision: str,
        dimensions: Dict[str, float],
        dimension_tags: Optional[Sequence[str]] = None,
        reflection_id: Optional[int] = None,
    ) -> Dict[str, float]:
        decision_u = (decision or "").upper()
        reward = 0.0
        if decision_u in ("APPROVE_CLI", "APPROVE_IDE", "APPROVE"):
            reward = 1.0
        elif decision_u == "REJECT":
            reward = -1.0
        elif decision_u == "HOLD":
            reward = 0.0

        before = await self.get_weights()
        after = dict(before)
        dims = {k: float(dimensions.get(k, 0.0)) for k in DIM_KEYS}
        mean_d = sum(dims.values()) / max(len(DIM_KEYS), 1)
        focus = list(dimension_tags or [])
        if not focus and reward != 0:
            # top-2 dims of the idea
            focus = [k for k, _ in sorted(dims.items(), key=lambda kv: kv[1], reverse=True)[:2]]
        if decision_u == "HOLD":
            focus = ["claim_clarity"]

        for k in DIM_KEYS:
            credit = 1.0 if (not focus or k in focus) else 0.35
            after[k] = after[k] + WEIGHT_ETA * reward * credit * ((dims[k] / 100.0) - (mean_d / 100.0))
        after = clamp_weights(after)

        if self.db_pool:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE patent_rank_weight_state
                    SET weights = $1::jsonb, updated_at = NOW(), update_count = update_count + 1
                    WHERE id = 1
                    """,
                    json.dumps(after),
                )
                await conn.execute(
                    """
                    INSERT INTO patent_rank_weight_history
                        (weights_before, weights_after, reflection_id, decision)
                    VALUES ($1::jsonb, $2::jsonb, $3, $4)
                    """,
                    json.dumps(before), json.dumps(after), reflection_id, decision_u[:32],
                )
        return after

    async def apply_ceo_feedback(
        self,
        library_id: int,
        *,
        decision: str,
        note: str = "",
        dimensions: Optional[Dict[str, float]] = None,
        dimension_tags: Optional[Sequence[str]] = None,
        reflection_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        if not self.db_pool:
            return {"status": "error", "error": "no_db"}
        decision_u = (decision or "").upper()
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM patent_idea_library WHERE id = $1", library_id
            )
        if not row:
            return {"status": "error", "error": "not_found"}
        dims = dimensions
        if dims is None:
            rd = row["rank_dimensions"]
            if isinstance(rd, str):
                dims = json.loads(rd)
            else:
                dims = dict(rd or {})
        await self.adapt_weights(
            decision=decision_u,
            dimensions=dims or {},
            dimension_tags=dimension_tags,
            reflection_id=reflection_id,
        )
        new_status = row["library_status"]
        score = float(row["rank_score"] or 0)
        if decision_u == "REJECT":
            new_status = "shelved"
            score = round(score * 0.7, 2)
        elif decision_u in ("APPROVE_CLI",):
            new_status = "implemented"
        elif decision_u in ("APPROVE_IDE",):
            new_status = "published_ide"
        elif decision_u == "HOLD":
            new_status = "active"
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE patent_idea_library SET
                    library_status = $2,
                    rank_score = $3,
                    ceo_feedback_note = $4,
                    updated_at = NOW(),
                    next_renew_at = CASE
                        WHEN $5 = 'HOLD' THEN NOW() + INTERVAL '7 days'
                        WHEN $5 = 'REJECT' THEN NOW() + INTERVAL '30 days'
                        ELSE next_renew_at
                    END
                WHERE id = $1
                """,
                library_id, new_status, score, (note or "")[:2000], decision_u,
            )
        return {"status": "ok", "library_status": new_status, "rank_score": score}

    async def spawn_variants(self, parent_id: int, *, max_n: int = 2) -> List[Dict[str, Any]]:
        if not self.db_pool:
            return []
        async with self.db_pool.acquire() as conn:
            parent = await conn.fetchrow(
                "SELECT * FROM patent_idea_library WHERE id = $1", parent_id
            )
        if not parent:
            return []
        out = []
        angles = [
            "adjacent claim angle — enablement deepening",
            "cross-category leverage — platform + QEC bridge",
        ]
        for i in range(min(max_n, len(angles))):
            title = f"{parent['title']} — variant {i+1}"
            summary = f"{parent['idea_summary']}\n\nVariant focus: {angles[i]}"
            res = await self.upsert_from_study(
                title=title,
                category=parent["primary_category"],
                topics=list(parent["topics"] or []) + [f"variant_{i+1}"],
                summary=summary[:4000],
                reflection_md=f"Spawned from parent {parent_id}: {angles[i]}",
                source_paths=list(parent["source_patent_paths"] or []),
                has_proven_anchor=True,
                parent_id=parent_id,
                force_new=True,
            )
            if res.get("status") == "ok":
                # start score ≈ parent * 0.85
                lid = int(res["library_id"])
                async with self.db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE patent_idea_library
                        SET rank_score = LEAST(rank_score, $2)
                        WHERE id = $1
                        """,
                        lid, round(float(parent["rank_score"] or 0) * 0.85, 2),
                    )
                out.append(res)
        return out

    def list_allowlisted_patents(self) -> List[str]:
        if not os.path.isdir(self.patent_root):
            return []
        out = []
        for name in sorted(os.listdir(self.patent_root)):
            if not name.endswith(".md"):
                continue
            if name.startswith("."):
                continue
            if "sandbox_reflections" in name:
                continue
            # Official corpus only
            if name.startswith("QUANTUM_") or name.startswith("PATENT_"):
                out.append(os.path.join(self.patent_root, name))
        return out

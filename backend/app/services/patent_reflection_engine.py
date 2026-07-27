"""Patent study → categorized library; promote → CEO review reflections.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger("patent_reflection_engine")

from app.services.patent_idea_library_engine import (
    CATEGORIES,
    PatentIdeaLibraryEngine,
    pick_study_category,
    patent_reflections_enabled,
)


def _adversarial_critique(excerpt: str) -> tuple[str, int]:
    """Generate 3 attack bullets; count how many 'land' via keyword heuristics."""
    text = (excerpt or "").lower()
    bullets = [
        "Prior art risk: overlapping published methods may anticipate key elements.",
        "Enablement risk: claim scope may lack sufficient structural detail for practice.",
        "Claim overlap: may collide with an existing provisional family in the portfolio.",
    ]
    hits = 0
    if any(w in text for w in ("known", "existing", "standard", "prior")):
        hits += 1
    if len(text) < 400:
        hits += 1
    if any(w in text for w in ("coherence", "emotion", "quantum", "odpe", "crystal")):
        hits += 1  # portfolio crowding
    md = "\n".join(f"- {b}" for b in bullets)
    if hits >= 2:
        md += "\n\n_Critique pressure applied (≥2 hits)._\n"
    return md, min(3, hits)


class PatentReflectionEngine:
    def __init__(self, db_pool, *, library_engine: Optional[PatentIdeaLibraryEngine] = None):
        self.db_pool = db_pool
        self.lib = library_engine or PatentIdeaLibraryEngine(db_pool)

    async def study_once(self, *, category: Optional[str] = None) -> Dict[str, Any]:
        if not patent_reflections_enabled():
            return {"status": "skipped", "reason": "flag_off"}
        remaining = await self.lib.study_cap_remaining()
        if remaining <= 0:
            return {"status": "skipped", "reason": "study_cap", "cap": 3}

        cat = category if category in CATEGORIES else pick_study_category(random.random())
        paths = self.lib.list_allowlisted_patents()
        if not paths:
            return {"status": "skipped", "reason": "no_patent_corpus"}

        # Prefer category-aligned filenames
        prefer = {
            "qec_quantum": ("QUANTUM_", "ODPE", "NEURAL", "EMOTIONAL", "FIELD"),
            "platform": ("VOICE", "LIMINAL", "CRYSTAL", "GOVERNING"),
            "queens_nate": ("NEURO", "UNIFIED", "CRYSTAL"),
            "world_qol": ("LIMINAL", "VOICE", "EMOTIONAL"),
        }
        keys = prefer.get(cat, ())
        ranked = sorted(
            paths,
            key=lambda p: (0 if any(k in os.path.basename(p).upper() for k in keys) else 1, p),
        )
        # mix: 60% preferred gap, 25% approve-adjacent handled elsewhere, 15% random
        roll = random.random()
        if roll < 0.15:
            src = random.choice(paths)
        else:
            src = ranked[0] if ranked else random.choice(paths)

        try:
            with open(src, "r", encoding="utf-8", errors="replace") as f:
                body = f.read(12000)
        except Exception as e:
            return {"status": "error", "error": f"read_failed:{e}"}

        base = os.path.basename(src)
        # Extract a light claim/summary snippet
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        claimish = [ln for ln in lines if re.search(r"claim|wherein|method|system", ln, re.I)]
        snippet = "\n".join((claimish or lines)[:40])[:3500]
        title = f"{cat}: insight from {base.replace('.md', '')}"[:280]
        summary = (
            f"Mission category `{cat}`. Grounded study of `{base}` for "
            f"world QoL / platform / QEC / Queens+Nate advancement with proven possibility.\n\n"
            f"{snippet[:1200]}"
        )
        reflection = (
            f"## Dual-COO study ({cat})\n\n"
            f"Source patent: `{base}`\n\n"
            f"### Observed hooks\n{snippet[:2000]}\n\n"
            f"### Proposed direction\n"
            f"Extend portfolio utility without rewriting filed claims — "
            f"sandbox reflection only. Align to category `{cat}`.\n"
        )
        critique_md, critique_hits = _adversarial_critique(snippet)
        topics = self._topics_for(cat, base)

        res = await self.lib.upsert_from_study(
            title=title,
            category=cat,
            topics=topics,
            summary=summary,
            reflection_md=reflection,
            source_paths=[src],
            critique_md=critique_md,
            critique_hits=critique_hits,
            has_proven_anchor=True,
        )
        return res

    def _topics_for(self, category: str, filename: str) -> List[str]:
        topics = [category]
        fn = filename.lower()
        if "odpe" in fn:
            topics.append("odpe")
        if "voice" in fn:
            topics.append("voice_pipeline")
        if "crystal" in fn:
            topics.append("crystal_memory")
        if "neural" in fn or "mirror" in fn:
            topics.append("neural_mirror")
        if "field" in fn or "quantum" in fn:
            topics.append("qec_field")
        if "liminal" in fn:
            topics.append("liminal_resolve")
        return topics[:8]

    async def promote_from_library(
        self, library_id: int, *, promote_reason: str = "exploit"
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
                return {"status": "skipped", "reason": "archived"}
            # Avoid duplicate open reflections
            open_id = await conn.fetchval(
                """
                SELECT id FROM patent_reflections
                WHERE library_id = $1
                  AND status IN ('pending', 'inquiring', 'ready_for_decision')
                LIMIT 1
                """,
                library_id,
            )
            if open_id:
                return {"status": "skipped", "reason": "already_promoted", "reflection_id": int(open_id)}

            rid = await conn.fetchval(
                """
                INSERT INTO patent_reflections (
                    library_id, title, primary_category, topics, source_patent_paths,
                    reflection_md, idea_summary, proposed_claims_json,
                    sandbox_path, promote_reason, status, risk_class, proposed_by
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,'[]'::jsonb,$8,$9,'pending','YELLOW','dual_coo'
                ) RETURNING id
                """,
                library_id,
                row["title"],
                row["primary_category"],
                list(row["topics"] or []),
                list(row["source_patent_paths"] or []),
                row["latest_reflection_md"] or "",
                row["idea_summary"] or "",
                row["sandbox_path"],
                promote_reason[:16],
            )
            await conn.execute(
                """
                UPDATE patent_idea_library SET
                    library_status = 'promoted',
                    promote_reason = $2,
                    promote_count = promote_count + 1,
                    updated_at = NOW()
                WHERE id = $1
                """,
                library_id, promote_reason[:16],
            )

        # CEO YELLOW enqueue
        ceo_item = None
        try:
            from app.websocket.cli_dual_coo import RISK_YELLOW, enqueue_ceo

            enq = enqueue_ceo(
                risk=RISK_YELLOW,
                title=f"Patent review: {row['title'][:120]}",
                detail=(
                    f"category={row['primary_category']} score={row['rank_score']} "
                    f"reason={promote_reason}. Open Patent Review tab."
                ),
                origin="dual_coo",
                task_id=f"patent-reflect-{rid}",
                payload={
                    "kind": "patent_reflect",
                    "reflection_id": int(rid),
                    "library_id": library_id,
                    "ask_of_ceo": "Inquire, then APPROVE_CLI / APPROVE_IDE / REJECT / HOLD",
                    "patent_review_path": f"patent_review.html#id={int(rid)}",
                },
                dedup_ttl_s=86400,
            )
            ceo_item = enq.get("id") if isinstance(enq, dict) else None
            if ceo_item and self.db_pool:
                async with self.db_pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE patent_reflections SET ceo_item_id = $2 WHERE id = $1",
                        rid, str(ceo_item)[:120],
                    )
        except Exception as e:
            logger.warning("CEO enqueue patent reflect: %s", e)

        return {
            "status": "ok",
            "reflection_id": int(rid),
            "library_id": library_id,
            "promote_reason": promote_reason,
            "ceo_item_id": ceo_item,
        }

    async def get_reflection(self, reflection_id: int) -> Optional[Dict[str, Any]]:
        if not self.db_pool:
            return None
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM patent_reflections WHERE id = $1", reflection_id
            )
            if not row:
                return None
            inqs = await conn.fetch(
                """
                SELECT * FROM patent_reflection_inquiries
                WHERE reflection_id = $1
                ORDER BY created_at ASC
                """,
                reflection_id,
            )
        d = dict(row)
        for k, v in list(d.items()):
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        d["inquiries"] = []
        for iq in inqs:
            q = dict(iq)
            for k, v in list(q.items()):
                if hasattr(v, "isoformat"):
                    q[k] = v.isoformat()
            d["inquiries"].append(q)
        return d

    async def list_reflections(
        self, *, status: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        if not self.db_pool:
            return []
        args: List[Any] = []
        where = "1=1"
        if status:
            args.append(status)
            where = f"status = ${len(args)}"
        args.append(max(1, min(limit, 200)))
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT r.*, l.rank_score AS library_rank_score
                FROM patent_reflections r
                LEFT JOIN patent_idea_library l ON l.id = r.library_id
                WHERE {where}
                ORDER BY r.created_at DESC
                LIMIT ${len(args)}
                """,
                *args,
            )
        out = []
        for r in rows:
            d = dict(r)
            for k, v in list(d.items()):
                if hasattr(v, "isoformat"):
                    d[k] = v.isoformat()
                elif k == "library_rank_score" and v is not None:
                    d[k] = float(v)
            out.append(d)
        return out

    async def add_inquiry(
        self,
        reflection_id: int,
        *,
        author: str,
        body: str,
        parent_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        if author not in ("ceo", "dual_coo", "queen_mac", "queen_cloud"):
            return {"status": "error", "error": "bad_author"}
        if not (body or "").strip():
            return {"status": "error", "error": "empty_body"}
        if not self.db_pool:
            return {"status": "error", "error": "no_db"}
        async with self.db_pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT 1 FROM patent_reflections WHERE id = $1", reflection_id
            )
            if not exists:
                return {"status": "error", "error": "not_found"}
            iid = await conn.fetchval(
                """
                INSERT INTO patent_reflection_inquiries
                    (reflection_id, author, body, parent_id)
                VALUES ($1, $2, $3, $4) RETURNING id
                """,
                reflection_id, author, body.strip()[:8000], parent_id,
            )
            await conn.execute(
                """
                UPDATE patent_reflections SET status = 'inquiring', updated_at = NOW()
                WHERE id = $1 AND status IN ('pending', 'inquiring')
                """,
                reflection_id,
            )
        # Auto dual_coo reply for CEO questions
        if author == "ceo":
            await self._auto_reply(reflection_id, body)
        return {"status": "ok", "inquiry_id": int(iid)}

    async def _auto_reply(self, reflection_id: int, question: str) -> None:
        if not self.db_pool:
            return
        refl = await self.get_reflection(reflection_id)
        if not refl:
            return
        reply = (
            f"Dual-COO reply: Regarding your inquiry — "
            f"category `{refl.get('primary_category')}`, "
            f"sources {', '.join((refl.get('source_patent_paths') or [])[:3])}. "
            f"We recommend focusing on proven-possibility anchors in the sandbox reflection. "
            f"(Q: {(question or '')[:240]})"
        )
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO patent_reflection_inquiries
                    (reflection_id, author, body)
                VALUES ($1, 'dual_coo', $2)
                """,
                reflection_id, reply[:8000],
            )

    async def mark_ready(self, reflection_id: int) -> Dict[str, Any]:
        if not self.db_pool:
            return {"status": "error", "error": "no_db"}
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT status FROM patent_reflections WHERE id = $1", reflection_id
            )
            if not row:
                return {"status": "error", "error": "not_found"}
            await conn.execute(
                """
                UPDATE patent_reflections
                SET status = 'ready_for_decision', updated_at = NOW()
                WHERE id = $1
                """,
                reflection_id,
            )
        return {"status": "ok", "reflection_id": reflection_id, "ready": True}

    async def decide(
        self,
        reflection_id: int,
        *,
        decision: str,
        reviewed_by: str = "DrNevedal1",
        dimension_tags: Optional[Sequence[str]] = None,
        note: str = "",
    ) -> Dict[str, Any]:
        decision_u = (decision or "").strip().upper()
        if decision_u not in ("REJECT", "HOLD", "APPROVE_CLI", "APPROVE_IDE"):
            return {"status": "error", "error": "bad_decision"}
        if not self.db_pool:
            return {"status": "error", "error": "no_db"}

        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM patent_reflections WHERE id = $1", reflection_id
            )
        if not row:
            return {"status": "error", "error": "not_found"}

        if decision_u in ("APPROVE_CLI", "APPROVE_IDE"):
            if row["status"] != "ready_for_decision":
                return {
                    "status": "error",
                    "error": "not_ready",
                    "detail": "Mark ready after inquiries before approve",
                }

        status_map = {
            "REJECT": "rejected",
            "HOLD": "held",
            "APPROVE_CLI": "approved_cli",
            "APPROVE_IDE": "approved_ide",
        }
        new_status = status_map[decision_u]
        ide_path = row["sandbox_path"]
        cli_task_id = None

        if decision_u == "APPROVE_IDE" and ide_path:
            # Ensure path recorded
            pass
        if decision_u == "APPROVE_CLI":
            cli_task_id = f"patent_implement_sandbox-{reflection_id}"
            try:
                from app.websocket.cli_task_bus import publish_task

                pub = publish_task(
                    origin="cloud",
                    kind="patent_implement_sandbox",
                    files=[],  # sandbox only — never lock official patent paths
                    notes=(
                        f"CEO APPROVE_CLI reflection={reflection_id} "
                        f"library={row['library_id']} path={ide_path or ''}"
                    )[:2000],
                )
                if isinstance(pub, dict):
                    tid = pub.get("task_id") or (pub.get("task") or {}).get("task_id")
                    if tid:
                        cli_task_id = str(tid)
            except Exception as e:
                logger.warning("CLI implement publish_task: %s", e)
                try:
                    from app.websocket.cli_dual_coo import RISK_YELLOW, enqueue_ceo

                    enqueue_ceo(
                        risk=RISK_YELLOW,
                        title=f"CLI implement patent sandbox #{reflection_id}",
                        detail=(row["idea_summary"] or "")[:500],
                        origin="ceo",
                        task_id=cli_task_id,
                        payload={
                            "kind": "patent_implement_sandbox",
                            "reflection_id": reflection_id,
                            "library_id": int(row["library_id"]),
                            "sandbox_path": ide_path,
                        },
                    )
                except Exception as e2:
                    logger.warning("CLI implement enqueue fallback: %s", e2)

        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE patent_reflections SET
                    status = $2,
                    ide_path = COALESCE($3, ide_path),
                    cli_task_id = COALESCE($4, cli_task_id),
                    reviewed_at = NOW(),
                    reviewed_by = $5,
                    updated_at = NOW()
                WHERE id = $1
                """,
                reflection_id, new_status, ide_path, cli_task_id, reviewed_by[:120],
            )

        fb = await self.lib.apply_ceo_feedback(
            int(row["library_id"]),
            decision=decision_u,
            note=note,
            dimension_tags=dimension_tags,
            reflection_id=reflection_id,
        )

        variants = []
        if decision_u in ("APPROVE_CLI", "APPROVE_IDE"):
            variants = await self.lib.spawn_variants(int(row["library_id"]), max_n=2)

        return {
            "status": "ok",
            "reflection_id": reflection_id,
            "decision": decision_u,
            "reflection_status": new_status,
            "ide_path": ide_path,
            "ide_open_url": f"ide.html?file={ide_path}" if ide_path and decision_u == "APPROVE_IDE" else None,
            "cli_task_id": cli_task_id,
            "library_feedback": fb,
            "variants": variants,
        }

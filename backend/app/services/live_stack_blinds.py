"""QUANTUM-CRYSTAL-ARCH — Live-stack (capability-track) blind generation.

Produces nate_response_live + live_stack_attempt. Never overwrites judge-track
nate_response / harness_thin_inference scores.
"""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

_BASE_CLIENT_PROMPT = (
    "You are Little Nate, a therapeutic AI companion. Speak in first person only. "
    "Never narrate your own eyes, voice, or body in third person. Never use stage "
    "directions. Be present, clinically sound, no fabrication."
)

_RP_IN_DELTA = re.compile(
    r"Failed move(?:\s*\(blind Nate\))?:\s*.{0,40}"
    r"(?:Nate'?s\s+(?:eyes|voice)|his voice cracks|\*[a-z]+)",
    re.I | re.S,
)


async def paraphrase_stem_for_live(client_says: str, router=None) -> str:
    stem = (client_says or "").strip()
    if not stem:
        return ""
    if router is None:
        return (
            stem.replace("I'm ", "I am ")
            .replace("I've ", "I have ")
            .replace("don't ", "do not ")
        ).strip()[:4000]
    try:
        result = await router.generate(
            prompt=(
                "Paraphrase the following CLIENT utterance only. Preserve clinical "
                "facts (SI/HI, ages, relationships, means). Do NOT answer as a "
                "therapist. Output the paraphrase alone.\n\n"
                f"{stem[:3500]}"
            ),
            system="Paraphrase engine. No therapy reply. No third-person Nate.",
            domain="utility",
            max_tokens=400,
            temperature=0.3,
        )
        if isinstance(result, dict):
            text = str(result.get("text") or result.get("response") or "").strip()
        else:
            text = str(result or "").strip()
        return (text if len(text) >= 20 else stem)[:4000]
    except Exception:
        return stem


async def run_live_stack_turn(
    *,
    pool,
    user_text: str,
    user_id: str,
) -> Dict[str, Any]:
    from app.services.sovereign_chat_client import generate_complete
    from app.services.therapeutic_controller import (
        audit_therapeutic_response,
        prepare_therapeutic_context,
    )

    if os.getenv("ENABLE_SYMBOLIC_VERIFIER", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        os.environ["ENABLE_SYMBOLIC_VERIFIER"] = "true"

    pack = await prepare_therapeutic_context(
        user_text=user_text,
        user_id=user_id,
        db_pool=pool,
        base_system_prompt=_BASE_CLIENT_PROMPT,
        default_max_tokens=600,
        session_id=f"live_stack_{uuid.uuid4().hex[:12]}",
    )
    enriched = pack.get("enriched_system_prompt") or _BASE_CLIENT_PROMPT
    max_tok = min(int(pack.get("max_tokens") or 600), 800)
    text, provider = await generate_complete(
        enriched,
        user_text,
        odpe_signal=None,
        domain="clinical",
        temperature=0.35,
        max_tokens=max_tok,
    )
    audit_meta = dict(pack.get("audit_metadata") or {})
    audit_meta.setdefault("max_tokens", max_tok)
    audit_meta.setdefault("user_text_for_audit", (user_text or "")[:800])
    audit = await audit_therapeutic_response(
        response_text=(text or "").strip(),
        audit_metadata=audit_meta,
        user_id=user_id,
        db_pool=pool,
        recent_narratives=None,
    )
    final = (audit or {}).get("response_text") or text or ""
    return {
        "text": final.strip()[:8000],
        "provider": provider,
        "audit_passed": bool((audit or {}).get("audit_passed", True)),
        "violations": (audit or {}).get("violations") or [],
        "crisis_inject": "Principal-Review" in (enriched or "")
        or "MUST:" in (enriched or ""),
        "max_tokens": max_tok,
    }


async def scrub_contaminated_deltas(conn) -> int:
    from app.services.principal_review_crisis_policy import (
        annotate_teaching_delta,
        scrub_teaching_text,
    )

    rows = await conn.fetch(
        """SELECT c.id, c.crystal_text, l.principal_response, l.nate_response,
                  l.section, l.id AS lib_id
           FROM nate_intelligence_crystals c
           JOIN principal_review_library l
             ON l.promoted_crystal_id = c.id::text
           WHERE c.origin_surface = 'principal_review'
             AND c.superseded_by IS NULL
             AND (
               c.crystal_text ILIKE '%Failed move%'
               OR c.crystal_text ILIKE '%Nate''s eyes%'
               OR c.crystal_text ILIKE '%his voice cracks%'
             )"""
    )
    fixed = 0
    for r in rows:
        old = r["crystal_text"] or ""
        principal = scrub_teaching_text(r["principal_response"] or "")
        nate = scrub_teaching_text(r["nate_response"] or "")
        section = str(r["section"] or "clinical")[:40]
        delta = annotate_teaching_delta(principal=principal, nate_blind=nate)
        parts = [
            f"[Principal-Review · {section}]",
            (
                "TEACHING RULE: Absorb principles, stance, safety moves, and clinical "
                "intent from Principal Guide. Never recite Guide text verbatim."
            ),
        ]
        if delta:
            parts.append(delta)
        if principal:
            parts.append(
                "Principal Guide (3/3/3 corrective underwriting — adapt, do not recite):\n"
                f"{principal[:2500]}"
            )
        new_text = scrub_teaching_text("\n".join(parts))
        if new_text == old or (
            "Failed move" in new_text and _RP_IN_DELTA.search(new_text)
        ):
            continue
        content_hash = hashlib.sha256(new_text.encode("utf-8")).hexdigest()
        await conn.execute(
            """UPDATE nate_intelligence_crystals
               SET crystal_text = $2, content_hash = $3
               WHERE id = $1""",
            r["id"],
            new_text,
            content_hash,
        )
        fixed += 1
    return fixed


async def generate_live_stack_batch(
    pool,
    *,
    scenario_ids: Optional[Sequence[str]] = None,
    scored_only: bool = True,
    limit: int = 50,
    user: str = "audit_client",
    force_rewrite: bool = False,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    run_id = run_id or (
        f"live_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_"
        f"{uuid.uuid4().hex[:8]}"
    )
    results: List[Dict[str, Any]] = []
    async with pool.acquire() as conn:
        if scenario_ids:
            rows = await conn.fetch(
                """SELECT id, scenario_id, section, client_says,
                          live_paraphrase_used, nate_response_live
                   FROM six_quotient_human_gold
                   WHERE scenario_id = ANY($1::text[])
                     AND COALESCE(is_degraded_distractor, false) = false
                   ORDER BY section, scenario_id
                   LIMIT $2""",
                list(scenario_ids),
                max(1, limit),
            )
        else:
            scored_clause = "human_scored = true" if scored_only else "TRUE"
            live_clause = (
                "TRUE" if force_rewrite else "COALESCE(nate_response_live, '') = ''"
            )
            rows = await conn.fetch(
                f"""SELECT id, scenario_id, section, client_says,
                          live_paraphrase_used, nate_response_live
                   FROM six_quotient_human_gold
                   WHERE COALESCE(is_degraded_distractor, false) = false
                     AND COALESCE(nate_response, '') <> ''
                     AND {scored_clause}
                     AND {live_clause}
                   ORDER BY section, scenario_id
                   LIMIT $1""",
                max(1, limit),
            )
        hw = await conn.fetchval(
            """SELECT hardware_id FROM users
               WHERE username = $1 OR hardware_id = $1 LIMIT 1""",
            user,
        )
        user_id = hw or user
        relabel = await conn.execute(
            """UPDATE six_quotient_human_gold
               SET response_provenance = 'harness_thin_inference'
               WHERE response_provenance = 'nate_genuine_attempt'
                 AND COALESCE(is_degraded_distractor, false) = false"""
        )
        scrubbed = await scrub_contaminated_deltas(conn)

    router = None
    try:
        from app.services.nate_inference_router import NateInferenceRouter

        router = NateInferenceRouter(app_state=None)
    except Exception:
        router = None

    for r in rows:
        stem = (r["client_says"] or "").strip()
        if not stem:
            results.append({"scenario_id": r["scenario_id"], "status": "skip_empty"})
            continue
        paraphrase = (r["live_paraphrase_used"] or "").strip() or await paraphrase_stem_for_live(
            stem, router
        )
        try:
            out = await run_live_stack_turn(
                pool=pool, user_text=paraphrase, user_id=user_id
            )
        except Exception as e:
            results.append(
                {"scenario_id": r["scenario_id"], "status": "fail", "error": str(e)[:200]}
            )
            continue
        text = out["text"]
        if not text:
            results.append({"scenario_id": r["scenario_id"], "status": "skip_empty_out"})
            continue
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE six_quotient_human_gold
                   SET nate_response_live = $2,
                       live_response_provenance = 'live_stack_attempt',
                       live_generated_at = NOW(),
                       live_stack_run_id = $3,
                       live_paraphrase_used = $4
                   WHERE id = $1""",
                r["id"],
                text,
                run_id,
                paraphrase[:4000],
            )
        results.append(
            {
                "scenario_id": r["scenario_id"],
                "status": "ok",
                "chars": len(text),
                "provider": out.get("provider"),
                "audit_passed": out.get("audit_passed"),
                "violations": (out.get("violations") or [])[:5],
            }
        )

    ok_n = sum(1 for x in results if x.get("status") == "ok")
    return {
        "status": "ok",
        "run_id": run_id,
        "written": ok_n,
        "attempted": len(results),
        "relabel": str(relabel),
        "scrubbed_deltas": scrubbed,
        "items": results,
    }

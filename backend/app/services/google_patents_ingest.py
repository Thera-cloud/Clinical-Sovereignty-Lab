"""Google Patents ingest — structured prior-art hits → prior_art_sweep_log + CEO flags.

Uses SecureSearchProxy (DuckDuckGo/Bing) with site:patents.google.com queries.
Not a proprietary Patents API client — worker-ant path for Dual-COO prior-art.

# QUANTUM-CRYSTAL-ARCH — patent portfolio coverage
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("google_patents_ingest")

_PATENT_NUM_RE = re.compile(
    r"\b((?:US|EP|WO|CN|JP)\s?\d{6,12}(?:[A-Z]\d?)?)\b",
    re.I,
)


def _normalize_hit(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {"title": str(raw)[:300], "url": "", "snippet": "", "patent_numbers": []}
    title = str(raw.get("title") or raw.get("name") or "")[:300]
    url = str(raw.get("url") or raw.get("href") or raw.get("link") or "")[:500]
    body = str(
        raw.get("body") or raw.get("snippet") or raw.get("description") or ""
    )[:800]
    nums = list({m.group(1).replace(" ", "").upper() for m in _PATENT_NUM_RE.finditer(
        f"{title} {body} {url}"
    )})[:5]
    return {
        "title": title,
        "url": url,
        "snippet": body,
        "patent_numbers": nums,
    }


async def search_google_patents(
    query: str,
    *,
    coach_id: str = "google_patents_ingest",
    num_results: int = 5,
) -> Dict[str, Any]:
    """Run a patents.google.com-scoped search; return normalized hits."""
    q = (query or "").strip()
    if not q:
        return {"status": "error", "error": "empty_query", "hits": []}
    if "patents.google.com" not in q.lower():
        q = f"site:patents.google.com {q}"
    hits: List[Dict[str, Any]] = []
    try:
        from app.services.search_proxy import SecureSearchProxy

        data_dir = os.getenv("DATA_DIR", "/tmp/nate_prior_art")
        os.makedirs(data_dir, exist_ok=True)
        proxy = SecureSearchProxy(data_dir=data_dir)
        result = await proxy.execute_search(
            q, coach_id=coach_id, num_results=max(1, min(num_results, 8)),
        )
        raw_list = []
        if isinstance(result, dict):
            raw_list = list(result.get("results") or [])[:num_results]
        hits = [_normalize_hit(h) for h in raw_list]
        return {
            "status": "ok",
            "query": q[:500],
            "hits": hits,
            "count": len(hits),
        }
    except Exception as e:
        logger.warning("google_patents_ingest search failed: %s", e)
        return {"status": "error", "error": str(e)[:300], "hits": [], "query": q[:500]}


async def ingest_patent_crystal_sweep(
    db_pool,
    *,
    crystal_id: int,
    snippet: str,
    risk_class: str = "YELLOW",
) -> Dict[str, Any]:
    """Search + persist one crystal's prior-art sweep row."""
    if not db_pool:
        return {"status": "skipped"}
    search = await search_google_patents((snippet or "")[:120])
    hits = list(search.get("hits") or [])
    query = str(search.get("query") or "")[:500]
    hits_payload = json.dumps(hits, default=str)
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO prior_art_sweep_log
                    (query_text, crystal_id, hits_json, status, risk_class)
                VALUES ($1, $2, $3::jsonb, $4, $5)
                """,
                query,
                int(crystal_id),
                hits_payload,
                "proposed" if hits else "empty",
                risk_class[:16],
            )
        if hits:
            from app.websocket.cli_dual_coo import RISK_YELLOW, enqueue_ceo

            enqueue_ceo(
                risk=RISK_YELLOW,
                title=f"Prior-art hits for crystal {crystal_id}",
                detail=query[:300],
                origin="cloud",
                task_id=f"prior_art:{crystal_id}",
                payload={
                    "crystal_id": int(crystal_id),
                    "hits": len(hits),
                    "patent_numbers": [
                        n for h in hits for n in (h.get("patent_numbers") or [])
                    ][:10],
                },
                dedup_ttl_s=12 * 3600,
            )
        return {
            "status": "ok",
            "crystal_id": int(crystal_id),
            "hits": len(hits),
            "search_status": search.get("status"),
        }
    except Exception as e:
        logger.warning("ingest_patent_crystal_sweep: %s", e)
        return {"status": "error", "error": str(e)[:200]}


async def portfolio_coverage_seed(db_pool, *, max_propose: int = 8) -> int:
    """If patent_claim_map is thin, propose additional claim tags."""
    if not db_pool:
        return 0
    try:
        from app.services.patent_claim_guardian import propose_claim_tag

        async with db_pool.acquire() as conn:
            nmap = await conn.fetchval("SELECT COUNT(*) FROM patent_claim_map")
        if int(nmap or 0) >= 12:
            return 0
        extras = [
            ("provisional_6_odpe", "claim_resonance",
             "backend/app/services/odpe_engine.py", "ODPEEngine"),
            ("provisional_7_liminal", "claim_liminal_resolve",
             "backend/app/services/language_drift_monitor.py", "LanguageDriftMonitor"),
            ("provisional_8_voice", "claim_voice_pipeline",
             "backend/app/services/twilio_grok_xtts_pipeline.py", "handle_media_stream"),
            ("provisional_9_neuro", "claim_neural_mirror",
             "backend/app/services/neural_mirror.py", "NeuralMirrorSession"),
            ("provisional_11_mirror", "claim_eeg_fingerprint",
             "backend/app/services/neural_mirror.py", "NeuralMirrorSession"),
            ("provisional_5_crystal", "claim_decay",
             "backend/app/services/nate_memory_crystallizer.py", "_decay_cycle"),
            ("provisional_3_visual", "claim_visual_biometrics",
             "backend/app/services/nevedal_engine.py", "VoiceBiometricExtractor"),
            ("foundation_qec", "claim_c_emo",
             "backend/app/services/nevedal_engine.py", "compute_emotional_coherence"),
        ]
        proposed = 0
        for fam, cref, path, fn in extras[:max_propose]:
            await propose_claim_tag(
                db_pool,
                family_id=fam,
                claim_ref=cref,
                code_path=path,
                function_name=fn,
                claim_text=f"Auto-proposed from portfolio coverage: {fam}",
                proposed_by="google_patents_ingest",
            )
            proposed += 1
        return proposed
    except Exception as e:
        logger.warning("portfolio_coverage_seed: %s", e)
        return 0

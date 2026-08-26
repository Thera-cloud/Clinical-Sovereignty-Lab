"""AlphaLN Phase B — validated-instrument scorer (WAI-SR / SRS / PHQ-9 proxy).

LLM judge uses Grok Foundry credentials from ``nate_ai_config``. Two-run
agreement is required before a validated method is returned; disagreement
falls back to heuristic_v1 so the shadow ledger still gets a row.

Does not write production crystals. Isolation: scores land only in
``alphaln_shadow_observations`` via the observer.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("nate.alphaln_validated_scorer")

AGREEMENT_THRESHOLD = 0.50  # abs delta on instrument mean (1–5 or 0–10)
WAI_ITEMS = 12
SRS_ITEMS = 4

_WAI_PROMPT = (
    "Score this therapy-style transcript on the 12-item Working Alliance "
    "Inventory Short Revised (WAI-SR). Each item 1-5. Return JSON only: "
    '{"item_scores": [12 floats], "notes": "one sentence"}.\n\nTRANSCRIPT:\n'
)
_SRS_PROMPT = (
    "Score this session on the 4-item Session Rating Scale (relationship, "
    "goals, approach, overall). Each item 0-10. Return JSON only: "
    '{"item_scores": [4 floats], "notes": "one sentence"}.\n\nTRANSCRIPT:\n'
)


def _clip(xs: List[float], lo: float, hi: float, n: int) -> List[float]:
    out = []
    for v in (xs or [])[:n]:
        try:
            out.append(max(lo, min(hi, float(v))))
        except (TypeError, ValueError):
            out.append(lo)
    while len(out) < n:
        out.append(lo)
    return out[:n]


def _mean(xs: List[float]) -> float:
    return round(sum(xs) / len(xs), 3) if xs else 0.0


async def _judge_once(prompt: str) -> Dict[str, Any]:
    """Single Grok Foundry judge call. Isolated for tests to monkeypatch."""
    from app.services.nate_ai_config import (
        NATE_CHAT_URL,
        nate_chat_headers,
        nate_chat_payload,
    )

    try:
        import httpx
    except ImportError:
        return {"item_scores": [], "notes": "httpx_unavailable"}

    payload = nate_chat_payload(
        messages=[{"role": "user", "content": prompt[:12000]}],
        max_tokens=400,
        temperature=0.1,
    )
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                NATE_CHAT_URL, headers=nate_chat_headers(), json=payload
            )
        resp.raise_for_status()
        body = resp.json()
        text = (
            (((body.get("choices") or [{}])[0].get("message") or {}).get("content"))
            or ""
        )
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return {"item_scores": [], "notes": "no_json"}
        parsed = json.loads(text[start : end + 1])
        return {
            "item_scores": parsed.get("item_scores") or [],
            "notes": str(parsed.get("notes") or "")[:500],
        }
    except Exception as exc:
        logger.warning("alphaln validated scorer judge failed: %s", exc)
        return {"item_scores": [], "notes": f"judge_error:{type(exc).__name__}"}


async def _two_run(
    prompt: str,
    n_items: int,
    lo: float,
    hi: float,
    judge: Optional[Callable] = None,
) -> Dict[str, Any]:
    fn = judge or _judge_once
    a = await fn(prompt)
    b = await fn(prompt)
    sa = _clip(a.get("item_scores") or [], lo, hi, n_items)
    sb = _clip(b.get("item_scores") or [], lo, hi, n_items)
    ma, mb = _mean(sa), _mean(sb)
    agreed = abs(ma - mb) < AGREEMENT_THRESHOLD and sa and sb and min(sa) > lo - 0.01
    # Average items when agreed; otherwise empty (caller falls back).
    items = [round((x + y) / 2.0, 3) for x, y in zip(sa, sb)] if agreed else []
    notes = (a.get("notes") or "") + (" | " + (b.get("notes") or "") if b.get("notes") else "")
    return {
        "score": _mean(items) if agreed else 0.0,
        "item_scores": items,
        "notes": notes.strip(" |")[:800],
        "agreed": agreed,
        "run_delta": round(abs(ma - mb), 3),
    }


async def score_wai_sr(
    transcript: str,
    judge: Optional[Callable] = None,
) -> Dict[str, Any]:
    raw = await _two_run(_WAI_PROMPT + (transcript or ""), WAI_ITEMS, 1.0, 5.0, judge)
    return {
        "score": raw["score"],
        "item_scores": raw["item_scores"],
        "notes": raw["notes"],
        "agreed": raw["agreed"],
        "run_delta": raw["run_delta"],
        "score_method": "wai_sr_v1",
    }


async def score_srs(
    transcript: str,
    judge: Optional[Callable] = None,
) -> Dict[str, Any]:
    raw = await _two_run(_SRS_PROMPT + (transcript or ""), SRS_ITEMS, 0.0, 10.0, judge)
    return {
        "score": raw["score"],
        "item_scores": raw["item_scores"],
        "notes": raw["notes"],
        "agreed": raw["agreed"],
        "run_delta": raw["run_delta"],
        "score_method": "srs_v1",
    }


def score_phq9_delta(before_state: Dict[str, Any], after_state: Dict[str, Any]) -> Dict[str, Any]:
    """Proxy PHQ-9 delta from synthetic client state (no live client PHI)."""
    def _mood(st: Optional[Dict[str, Any]]) -> float:
        st = st or {}
        # Higher affect / lower trust ≈ more depressive load (0–27 scale proxy).
        affect = float(st.get("affect") or st.get("phq9") or 0.5)
        trust = float(st.get("trust") or 0.5)
        return max(0.0, min(27.0, (affect * 18.0) + ((1.0 - trust) * 9.0)))

    before = _mood(before_state)
    after = _mood(after_state)
    delta = round(after - before, 3)  # negative = improvement
    return {
        "score": delta,
        "item_scores": [round(before, 3), round(after, 3)],
        "notes": f"proxy_phq9 before={before:.2f} after={after:.2f}",
        "score_method": "phq9_delta_v1",
        "agreed": True,
    }


async def score_validated_bundle(
    transcript: str,
    judge: Optional[Callable] = None,
    before_state: Optional[Dict[str, Any]] = None,
    after_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Primary observer entry. Crystallize only when WAI-SR two-run agrees."""
    wai = await score_wai_sr(transcript, judge=judge)
    if not wai.get("agreed"):
        return {
            "score": 0.0,
            "dims": {"validated_disagreement": True, "run_delta": wai.get("run_delta")},
            "score_method": "heuristic_v1",
            "notes": "wai_sr two-run disagreement; not crystallized as validated",
            "item_scores": [],
        }
    srs = await score_srs(transcript, judge=judge)
    phq = score_phq9_delta(before_state or {}, after_state or {})
    # Normalize WAI 1–5 mean onto 0–1 for the observer ``score`` column.
    norm = round((float(wai["score"]) - 1.0) / 4.0, 3)
    return {
        "score": max(0.0, min(1.0, norm)),
        "dims": {
            "wai_sr": wai["score"],
            "srs": srs["score"] if srs.get("agreed") else None,
            "phq9_delta": phq["score"],
        },
        "score_method": "wai_sr_v1",
        "notes": wai.get("notes") or "",
        "item_scores": wai.get("item_scores") or [],
        "srs": srs,
        "phq9": phq,
    }


def scorer_mode() -> str:
    return (os.getenv("ALPHALN_SCORER_MODE") or "heuristic_v1").strip().lower()

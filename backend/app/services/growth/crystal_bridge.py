"""Marketing crystal bridge — allowed-source harvest + FederatedSearch recall.

Hard-rejects try/crisis/PII evidence. domain=marketing only.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("nate.growth.crystal_bridge")

ALLOWED_SOURCES: Set[str] = {
    "skyeye_activity",
    "skyeye_post_analytics",
    "bwas_weekly",
    "try_theme_weekly",
    "keyword_queue",
    "marketing_content",
    "funnel_routing_log",
    "content_ab_tests",
    "growth_diagnostics",
    "agent:MarketingIntelligence",
}

DENIED_SOURCES: Set[str] = {
    "public_trial",
    "public_trial_merge",
    "try_html",
    "anonymous_trial",
    "flagged_turn",
    "public_trial_flagged",
    "trial_merge",
    "public_summon",
}

_CRISIS_RE = re.compile(
    r"\b(suicid|kill myself|end my life|self[- ]?harm|want to die)\b",
    re.I,
)
_PII_RE = re.compile(
    r"(\b\d{3}-\d{2}-\d{4}\b|"  # SSN
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b|"  # email
    r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b)",  # phone
    re.I,
)


def reject_reason(text: str, source: str) -> Optional[str]:
    src = (source or "").strip()
    if src in DENIED_SOURCES or src.startswith("public_trial"):
        return "denied_source"
    if src not in ALLOWED_SOURCES and not src.startswith("agent:Marketing"):
        return "source_not_allowlisted"
    body = text or ""
    if _CRISIS_RE.search(body):
        return "crisis"
    if _PII_RE.search(body):
        return "pii"
    if len(body.strip()) < 40:
        return "too_short"
    return None


def harvest_marketing_insight(
    app_state,
    *,
    text: str,
    source: str,
) -> Dict[str, Any]:
    """Append to crystallizer harvest buffer if allowed. Never raises."""
    reason = reject_reason(text, source)
    if reason:
        return {"ok": False, "rejected": reason}
    crystallizer = getattr(app_state, "nate_memory_crystallizer", None) if app_state else None
    if not crystallizer or not hasattr(crystallizer, "_harvest_buffer"):
        return {"ok": False, "rejected": "no_crystallizer"}
    crystallizer._harvest_buffer.append(
        {
            "text": (text or "")[:2000],
            "source": source,
            "domain": "marketing",
            "scope": "global",
            "created_at": datetime.now(timezone.utc),
        }
    )
    return {"ok": True, "domain": "marketing"}


async def recall_marketing(
    db_pool,
    query: str,
    *,
    app_state=None,
    limit: int = 5,
) -> str:
    """FederatedSearch domain=marketing. Empty string on failure."""
    q = (query or "").strip()[:1000]
    if not q:
        return ""
    try:
        coord = None
        if app_state is not None:
            coord = getattr(app_state, "federated_search", None)
        if coord is None:
            from app.services.quantum_knowledge_field import FederatedSearchCoordinator

            coord = FederatedSearchCoordinator(db_pool=db_pool)
        result = await coord.search(q, domain="marketing", include_devices=False)
        rows = (result or {}).get("results") or []
        parts = []
        for r in rows[:limit]:
            if (r.get("domain") or "marketing") not in ("marketing", None, ""):
                # Prefer marketing; allow unlabeled high-score hits from wisdom index
                if (r.get("score") or r.get("confidence") or 0) < 0.55:
                    continue
            txt = (r.get("crystal_text") or r.get("text") or r.get("content") or "")[:300]
            if txt:
                parts.append(f"- {txt}")
        return "\n".join(parts)
    except Exception as e:
        logger.debug("growth crystal_bridge recall failed: %s", e)
        return ""

"""Crystal domain allowlist. Canonical seven are never renamed (NG15)."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

CANONICAL_SEVEN = frozenset(
    {
        "clinical",
        "coaching",
        "marketing",
        "research",
        "culture",
        "defense",
        "general",
    }
)

ADDITIVE_DOMAINS = frozenset({"product", "coding", "operational"})

ORGANIC_EXTRA = frozenset(
    {
        "legal",
        "pmp",
        "machining",
        "teaching",
        "business",
        "accounting",
        "crisis",
        "liminal_resolve",
        "ln_self_curiosity",
    }
)

BUDGET_ALLOWLIST = CANONICAL_SEVEN | ADDITIVE_DOMAINS
VALID_DOMAINS = BUDGET_ALLOWLIST | ORGANIC_EXTRA

# marketing 24h inserts cannot exceed 2x clinical (floor 10).
MARKETING_TO_CLINICAL_MAX_RATIO = 2.0
MARKETING_BUDGET_FLOOR = 10

_ALIAS = {
    "therapeutic": "clinical",
    "operations": "operational",
    "cultural": "culture",
}

BLE_DOMAIN_BYTE = {
    "clinical": 1,
    "coaching": 2,
    "marketing": 3,
    "research": 4,
    "culture": 5,
    "defense": 6,
    "general": 7,
    "product": 8,
    "coding": 9,
    "operational": 10,
}


def normalize_domain(domain: Optional[str]) -> str:
    raw = (domain or "general").strip().lower()
    raw = _ALIAS.get(raw, raw)
    if raw not in VALID_DOMAINS:
        return "general"
    return raw


def marketing_crowds_clinical(counts_24h: Mapping[str, int]) -> bool:
    marketing = int(counts_24h.get("marketing") or 0)
    clinical = int(counts_24h.get("clinical") or 0)
    cap = max(int(clinical * MARKETING_TO_CLINICAL_MAX_RATIO), MARKETING_BUDGET_FLOOR)
    return marketing >= cap


async def allow_harvest(db_pool, domain: str) -> bool:
    domain = normalize_domain(domain)
    if domain != "marketing" or db_pool is None:
        return True
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
              COUNT(*) FILTER (WHERE domain = 'marketing') AS marketing,
              COUNT(*) FILTER (WHERE domain = 'clinical') AS clinical
            FROM nate_intelligence_crystals
            WHERE created_at > NOW() - INTERVAL '24 hours'
              AND COALESCE(scope, '') <> 'archived'
            """
        )
    counts = {
        "marketing": int((row or {}).get("marketing") or 0),
        "clinical": int((row or {}).get("clinical") or 0),
    }
    return not marketing_crowds_clinical(counts)


def pad_domain_rows(rows: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    by_domain = {str(r.get("domain")): dict(r) for r in rows if r.get("domain")}
    out: List[Dict[str, Any]] = []
    for domain in sorted(BUDGET_ALLOWLIST):
        if domain in by_domain:
            out.append(by_domain[domain])
        else:
            out.append(
                {
                    "domain": domain,
                    "crystal_count": 0,
                    "avg_confidence": 0,
                    "max_generation": 0,
                    "total_recalls": 0,
                }
            )
    for domain, row in by_domain.items():
        if domain not in BUDGET_ALLOWLIST:
            out.append(row)
    return out

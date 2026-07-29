"""Enrichment waterfall — skip vendors without API keys (no fake enrichment).

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("nate.growth.enrichment")

# Ordered waterfall. Each vendor needs its env key to run.
_VENDORS: List[Tuple[str, str]] = [
    ("apollo", "APOLLO_API_KEY"),
    ("clearbit", "CLEARBIT_API_KEY"),
    ("hunter", "HUNTER_API_KEY"),
]


def configured_vendors() -> List[str]:
    return [name for name, env in _VENDORS if (os.getenv(env) or "").strip()]


async def enrich_lead(lead: Dict[str, Any]) -> Dict[str, Any]:
    """Return {enrichment, runs[]} — never invent company data."""
    runs: List[Dict[str, Any]] = []
    enrichment = dict(lead.get("enrichment") or {})
    vendors = configured_vendors()
    if not vendors:
        runs.append(
            {
                "vendor": "none",
                "status": "skipped",
                "cost_usd": 0,
                "detail": {"reason": "no enrichment API keys configured"},
            }
        )
        return {"enrichment": enrichment, "runs": runs}

    for name, env in _VENDORS:
        if name not in vendors:
            runs.append(
                {
                    "vendor": name,
                    "status": "skipped",
                    "cost_usd": 0,
                    "detail": {"reason": f"{env} unset"},
                }
            )
            continue
        # Phase 3: record that the vendor is keyed but do not call live APIs
        # until credentials + spend approval are confirmed in production.
        runs.append(
            {
                "vendor": name,
                "status": "skipped",
                "cost_usd": 0,
                "detail": {
                    "reason": "keyed_but_live_call_deferred",
                    "env": env,
                },
            }
        )
        enrichment.setdefault("vendors_available", []).append(name)
    return {"enrichment": enrichment, "runs": runs}

"""
QUANTUM-CRYSTAL-ARCH: Crystal graph isolation audit + scope enforcement (Phase 5d).

Read-only helpers for proving cross-user / admin_only bleed cannot occur during traversal.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("nate.crystal_graph_isolation")

_RECALL_ALLOWED_SCOPES = frozenset({"global", "user"})
_BLOCKED_SCOPES = frozenset({"admin_only", "archived"})


def crystal_graph_enabled() -> bool:
    return os.getenv("ENABLE_CRYSTAL_GRAPH", "false").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def scope_allows_recall(scope: Optional[str], owner_user_id: Optional[str], requester_user_id: Optional[str]) -> bool:
    """Mirror crystal_recall_bridge allowlist — scope may only narrow, never widen."""
    s = (scope or "global").strip()
    if s in _BLOCKED_SCOPES:
        return False
    if s == "global":
        return owner_user_id is None
    if s.startswith("user:"):
        if not requester_user_id:
            return False
        suffix = s.split(":", 1)[1]
        return suffix in (requester_user_id, str(requester_user_id))
    return False


def enforce_traversal_scope(
    crystal: Dict[str, Any],
    requester_user_id: Optional[str],
) -> bool:
    """Return True if this crystal may be included in graph traversal for requester."""
    if not crystal:
        return False
    scope = crystal.get("scope")
    owner = crystal.get("user_id")
    if owner and requester_user_id and str(owner) != str(requester_user_id):
        return False
    return scope_allows_recall(scope, str(owner) if owner else None, requester_user_id)


async def audit_graph_traversal_isolation(
    db_pool: Any,
    *,
    seed_crystal_ids: List[str],
    requester_user_id: str,
    max_hops: int = 2,
) -> Dict[str, Any]:
    """
    Read-only BFS over crystal_edges; report any cross-boundary violations.
    Safe to run with ENABLE_CRYSTAL_GRAPH=false (audit-only).
    """
    report: Dict[str, Any] = {
        "requester_user_id": requester_user_id,
        "seed_count": len(seed_crystal_ids),
        "visited": 0,
        "violations": [],
        "blocked_edges": 0,
    }
    if not db_pool or not seed_crystal_ids or not requester_user_id:
        return report

    visited: Set[str] = set()
    frontier = list(seed_crystal_ids)
    hops = 0

    try:
        async with db_pool.acquire() as conn:
            while frontier and hops <= max_hops:
                next_frontier: List[str] = []
                for cid in frontier:
                    if cid in visited:
                        continue
                    visited.add(cid)
                    crystal = await conn.fetchrow(
                        """
                        SELECT id, scope, user_id, crystal_text
                        FROM nate_intelligence_crystals
                        WHERE id::text = $1 OR content_hash = $1
                        LIMIT 1
                        """,
                        str(cid),
                    )
                    if not crystal:
                        continue
                    report["visited"] += 1
                    cdict = dict(crystal)
                    if not enforce_traversal_scope(cdict, requester_user_id):
                        report["violations"].append(
                            {
                                "crystal_id": str(crystal["id"]),
                                "scope": crystal["scope"],
                                "reason": "scope_isolation",
                            }
                        )

                    edges = await conn.fetch(
                        """
                        SELECT crystal_a_hash, crystal_b_hash
                        FROM crystal_edges
                        WHERE crystal_a_hash = $1 OR crystal_b_hash = $1
                        LIMIT 50
                        """,
                        str(cid),
                    )
                    for e in edges:
                        neighbor = (
                            e["crystal_b_hash"]
                            if e["crystal_a_hash"] == str(cid)
                            else e["crystal_a_hash"]
                        )
                        if neighbor and neighbor not in visited:
                            next_frontier.append(neighbor)
                frontier = next_frontier
                hops += 1
    except Exception as e:
        logger.warning("crystal_graph_isolation: audit failed: %s", e)
        report["error"] = str(e)[:200]

    report["blocked_edges"] = len(report["violations"])
    return report


async def fetch_graph_surfaced_crystal_ids(db_pool: Any, limit: int = 200) -> List[int]:
    """Crystals reachable via at least one crystal_edges row (for PHI auditor extension)."""
    if not db_pool:
        return []
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT c.id
                FROM nate_intelligence_crystals c
                WHERE EXISTS (
                    SELECT 1 FROM crystal_edges e
                    WHERE e.crystal_a_hash = c.content_hash::text
                       OR e.crystal_b_hash = c.content_hash::text
                )
                AND c.scope IS DISTINCT FROM 'archived'
                ORDER BY c.id
                LIMIT $1
                """,
                limit,
            )
            return [int(r["id"]) for r in rows]
    except Exception as e:
        logger.warning("crystal_graph_isolation: fetch surfaced ids failed: %s", e)
        return []

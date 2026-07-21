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
    # QUANTUM-CRYSTAL-ARCH: DB personal crystals use scope='user' (not user:<id>)
    if s == "user":
        if owner_user_id is None:
            return True  # already filtered by recall SQL; verifier passes owner=None
        if not requester_user_id:
            return False
        return str(owner_user_id) == str(requester_user_id)
    if s.startswith("user:"):
        if not requester_user_id:
            return False
        suffix = s.split(":", 1)[1]
        if suffix in (requester_user_id, str(requester_user_id)):
            return True
        # QUANTUM-CRYSTAL-ARCH: legacy scope user:<username> with owner UUID match
        if owner_user_id and str(owner_user_id) == str(requester_user_id):
            return True
        return False
    return False


def enforce_traversal_scope(
    crystal: Dict[str, Any],
    requester_user_id: Optional[str],
    requester_aliases: Optional[Set[str]] = None,
) -> bool:
    """Return True if this crystal may be included in graph traversal for requester."""
    if not crystal:
        return False
    scope = crystal.get("scope")
    owner = crystal.get("user_id")
    if owner and requester_user_id and str(owner) != str(requester_user_id):
        return False
    s = (scope or "global").strip()
    if s.startswith("user:") and requester_aliases:
        suffix = s.split(":", 1)[1]
        if suffix in {str(a) for a in requester_aliases}:
            return True
    return scope_allows_recall(scope, str(owner) if owner else None, requester_user_id)


async def audit_graph_traversal_isolation(
    db_pool: Any,
    *,
    seed_crystal_ids: List[str],
    requester_user_id: str,
    max_hops: int = 2,
    requester_aliases: Optional[Set[str]] = None,
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
    aliases = set(requester_aliases or ())

    try:
        async with db_pool.acquire() as conn:
            while frontier and hops <= max_hops:
                next_frontier: List[str] = []
                for cid in frontier:
                    if cid in visited:
                        continue
                    visited.add(cid)
                    # QUANTUM-CRYSTAL-ARCH: edges store 16-char prefixes; crystals use 64-char SHA
                    key = str(cid)
                    key16 = key[:16]
                    crystal = await conn.fetchrow(
                        """
                        SELECT id, scope, user_id, crystal_text, content_hash
                        FROM nate_intelligence_crystals
                        WHERE id::text = $1
                           OR content_hash = $1
                           OR left(content_hash, 16) = left($1, 16)
                        LIMIT 1
                        """,
                        key,
                    )
                    if not crystal:
                        continue
                    report["visited"] += 1
                    cdict = dict(crystal)
                    if not enforce_traversal_scope(
                        cdict, requester_user_id, requester_aliases=aliases,
                    ):
                        report["violations"].append(
                            {
                                "crystal_id": str(crystal["id"]),
                                "scope": crystal["scope"],
                                "reason": "scope_isolation",
                            }
                        )

                    full_hash = str(crystal.get("content_hash") or key)
                    edges = await conn.fetch(
                        """
                        SELECT crystal_a_hash, crystal_b_hash
                        FROM crystal_edges
                        WHERE crystal_a_hash IN ($1, $2)
                           OR crystal_b_hash IN ($1, $2)
                        LIMIT 50
                        """,
                        full_hash,
                        full_hash[:16],
                    )
                    for e in edges:
                        a, b = str(e["crystal_a_hash"]), str(e["crystal_b_hash"])
                        neighbor = b if a in (full_hash, full_hash[:16], key16) else a
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
            # QUANTUM-CRYSTAL-ARCH: edge hashes are 16-char prefixes of content_hash
            rows = await conn.fetch(
                """
                WITH edge_keys AS (
                    SELECT DISTINCT crystal_a_hash AS h FROM crystal_edges
                    UNION
                    SELECT DISTINCT crystal_b_hash AS h FROM crystal_edges
                )
                SELECT c.id
                FROM nate_intelligence_crystals c
                JOIN edge_keys ek ON ek.h = left(c.content_hash::text, 16)
                WHERE c.scope IS DISTINCT FROM 'archived'
                  AND c.content_hash IS NOT NULL AND c.content_hash != ''
                ORDER BY c.id
                LIMIT $1
                """,
                limit,
            )
            return [int(r["id"]) for r in rows]
    except Exception as e:
        logger.warning("crystal_graph_isolation: fetch surfaced ids failed: %s", e)
        return []

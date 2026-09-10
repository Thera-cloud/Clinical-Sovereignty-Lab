"""Per-(user, topic-hash) recall fallback. Discard if no token overlap.

QUANTUM-CRYSTAL-ARCH — clinical. SOVEREIGN-STANDARD.
CEO: Nathaniel James Nevedal. Risk: RED.
"""

from __future__ import annotations

from typing import Any, Optional

from app.services.attunement import flags, store
from app.services.attunement.tokens import any_overlap, topic_hash

_TTL = 10 * 60


def _k(user_key: str, query: str) -> str:
    return store.key("rcache", user_key, topic_hash(query))


def store_recall(user_key: str, query: str, text: str, crystal_ids: Optional[list] = None) -> None:
    if not flags.recall_cache() or not user_key or not text:
        return
    store.set_json(
        _k(user_key, query),
        {"text": text[:6000], "crystal_ids": list(crystal_ids or [])[:50], "query": (query or "")[:200]},
        _TTL,
    )


def fetch(user_key: str, query: str) -> Any:
    """Serve cache only if FTS/token overlap with this query. Never cross-user."""
    if not flags.recall_cache() or not user_key:
        return ""
    payload = store.get_json(_k(user_key, query))
    if not payload:
        return ""
    text = payload.get("text") or ""
    if not any_overlap(query or "", text, min_hits=2):
        return ""
    return text

"""
Search context manager for Little Nate factual grounding.

Stores search results per user so the AI can reference them across
messages in the same session. Caps to MAX_SEARCH_RESULTS_KEPT entries
and MAX_SEARCH_CONTEXT_CHARS total to prevent context window bloat.
"""

from datetime import datetime, timezone

MAX_SEARCH_CONTEXT_CHARS = 4000
MAX_SEARCH_RESULTS_KEPT = 2

_user_search_contexts: dict[str, list[str]] = {}


def update_search_context(user_id: str, query: str, formatted_results: str) -> str:
    """Store search results for a user and return the combined context string."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry = (
        f"[SEARCH: \"{query}\" — retrieved {timestamp}]\n"
        f"{formatted_results}\n"
        f"[END SEARCH]"
    )

    history = _user_search_contexts.get(user_id, [])
    history.append(entry)
    if len(history) > MAX_SEARCH_RESULTS_KEPT:
        history = history[-MAX_SEARCH_RESULTS_KEPT:]
    _user_search_contexts[user_id] = history

    combined = "\n\n".join(history)
    if len(combined) > MAX_SEARCH_CONTEXT_CHARS:
        combined = combined[-MAX_SEARCH_CONTEXT_CHARS:]

    return (
        combined + "\n"
        "[INSTRUCTION: If these search results contradict something you said "
        "earlier in this conversation, acknowledge the correction naturally. "
        "Do not repeat raw search snippets — synthesize conversationally.]"
    )


def get_search_context(user_id: str) -> str:
    """Return the current stored search context for a user, or empty string."""
    history = _user_search_contexts.get(user_id)
    if not history:
        return ""
    combined = "\n\n".join(history)
    if len(combined) > MAX_SEARCH_CONTEXT_CHARS:
        combined = combined[-MAX_SEARCH_CONTEXT_CHARS:]
    return (
        combined + "\n"
        "[INSTRUCTION: If these search results contradict something you said "
        "earlier in this conversation, acknowledge the correction naturally. "
        "Do not repeat raw search snippets — synthesize conversationally.]"
    )


def clear_search_context(user_id: str) -> None:
    """Clear stored search context for a user (e.g. on session end)."""
    _user_search_contexts.pop(user_id, None)

"""
Session Assistant live chat — coach asks Nate mid-session with client memory.

Pulls crystal recall + recent conversation_history for the client, then
answers as a coach-side clinical assistant (not client-facing chat).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("session_assistant_chat")

_MODE_HINT = {
    "observe": "Provide a brief clinical observation. Do not prescribe interventions.",
    "suggest": "Offer one concrete intervention idea the coach can try next.",
    "challenge": "Respectfully challenge the coach's framing and push sharper clinical thinking.",
}


async def _load_client_memory(db_pool, client_id: str) -> str:
    """Crystal recall + recent main-chat turns for this client."""
    parts: List[str] = []
    if not db_pool or not client_id:
        return ""

    try:
        from app.websocket.crystal_recall_bridge import recall_crystals_for_context

        crystal_ctx = await recall_crystals_for_context(
            db_pool,
            client_id,
            max_results=6,
            source="session_assistant_chat",
        )
        if crystal_ctx:
            parts.append(crystal_ctx)
    except Exception as e:
        logger.warning("session_assistant_chat: crystal recall failed: %s", e)

    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT user_text, ai_text, created_at
                FROM conversation_history
                WHERE user_id = $1 OR user_id IN (
                    SELECT username FROM users
                    WHERE hardware_id = $1 OR username = $1
                    LIMIT 2
                )
                ORDER BY created_at DESC
                LIMIT 12
                """,
                client_id,
            )
        if rows:
            lines = []
            for r in reversed(list(rows)):
                ut = (r["user_text"] or "").strip()
                at = (r["ai_text"] or "").strip()
                if ut:
                    lines.append(f"Client: {ut[:400]}")
                if at:
                    lines.append(f"Nate: {at[:400]}")
            if lines:
                parts.append(
                    "[MAIN CHAT MEMORY — recent client Sanctuary chat]\n"
                    + "\n".join(lines[-20:])
                )
    except Exception as e:
        logger.warning("session_assistant_chat: conversation_history failed: %s", e)

    try:
        from app.services.pg_data_helpers import get_classroom_context_for_client_pg

        classroom = await get_classroom_context_for_client_pg(db_pool, client_id, limit=2)
        if classroom:
            parts.append(classroom)
    except Exception as e:
        logger.debug("session_assistant_chat: classroom context: %s", e)

    return "\n\n".join(parts)[:12000]


async def _llm_reply(system: str, user: str) -> str:
    """Prefer NateInferenceRouter; fall back to Azure chat."""
    try:
        from app.services.nate_inference_router import NateInferenceRouter

        router = NateInferenceRouter()
        result = await router.generate(
            prompt=user,
            system=system,
            domain="coaching",
            max_tokens=350,
            odpe_signal="PROVISIONAL",
        )
        text = ""
        if isinstance(result, dict):
            text = (result.get("text") or result.get("content") or "").strip()
        elif isinstance(result, str):
            text = result.strip()
        if text:
            return text
    except Exception as e:
        logger.warning("session_assistant_chat: router failed: %s", e)

    try:
        import httpx

        ep = (os.getenv("AZURE_OPENAI_ENDPOINT") or "").strip()
        key = (os.getenv("AZURE_API_KEY") or "").strip()
        dep = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o")
        if not ep or not key:
            return "Memory context loaded, but inference is unavailable right now."
        host = ep.replace("https://", "").replace("http://", "").rstrip("/")
        url = (
            f"https://{host}/openai/deployments/{dep}/chat/completions"
            f"?api-version=2024-06-01"
        )
        async with httpx.AsyncClient(timeout=25) as client:
            resp = await client.post(
                url,
                json={
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "max_completion_tokens": 350,
                },
                headers={"api-key": key},
            )
            if resp.status_code == 200:
                return (resp.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:
        logger.warning("session_assistant_chat: Azure fallback failed: %s", e)

    return "I could not generate a reply just now. Try again in a moment."


async def generate_coach_assist_reply(
    db_pool,
    *,
    client_id: str,
    coach_message: str,
    nate_mode: str = "suggest",
    client_name: str = "",
    recent_notes: Optional[List[str]] = None,
    chat_history: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Answer a coach question during a live session using client memory.

    Returns: {reply, memory_used, mode}
    """
    msg = (coach_message or "").strip()
    if not msg:
        return {"reply": "", "memory_used": False, "mode": nate_mode, "error": "empty"}

    mode = (nate_mode or "suggest").strip().lower()
    if mode not in _MODE_HINT:
        mode = "suggest"

    memory = await _load_client_memory(db_pool, client_id)
    notes_block = ""
    if recent_notes:
        clipped = [n.strip()[:300] for n in recent_notes[-8:] if (n or "").strip()]
        if clipped:
            notes_block = "[LIVE SESSION NOTES]\n" + "\n".join(f"- {n}" for n in clipped)

    history_block = ""
    if chat_history:
        lines = []
        for turn in chat_history[-10:]:
            role = (turn.get("role") or "").strip()
            content = (turn.get("content") or "").strip()[:500]
            if role and content:
                lines.append(f"{role}: {content}")
        if lines:
            history_block = "[THIS ASSISTANT THREAD]\n" + "\n".join(lines)

    system = f"""You are Little Nate, clinical AI assisting a coach DURING a live session with {client_name or 'the client'}.
You speak only to the COACH — never address the client directly.
Mode: {mode}. {_MODE_HINT[mode]}
Rules:
- Use MAIN CHAT MEMORY and crystals when relevant; say when you are drawing from prior chat.
- Keep replies under 120 words unless the coach asks for detail.
- Be concrete and clinically useful. No fluff, no banned sanctuary jargon (liminal, threshold, aching).
- If memory is empty or thin, say so and still offer a useful coaching prompt from the live note."""

    user = "\n\n".join(
        p
        for p in [
            memory or "[MEMORY: no prior chat/crystal context available]",
            notes_block,
            history_block,
            f"Coach asks: {msg}",
        ]
        if p
    )

    reply = await _llm_reply(system, user)
    return {
        "reply": reply,
        "memory_used": bool(memory),
        "mode": mode,
    }

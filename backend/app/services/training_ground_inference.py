"""Training Ground ILM inference — QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import logging

logger = logging.getLogger("training_ground")

ILM_GOVERNANCE = """
YOU ARE LITTLE NATE in Training Ground — Inner Leadership Mapping (ILM).

NON-CLINICAL MANDATE:
- Coaching mapping only — NOT therapy, NOT diagnosis, NOT trauma processing.
- NEVER guide unburdening, exile retrieval, childhood regression, or shadow excavation.
- If the user seeks clinical depth, redirect to mapping and coach visibility.

INNER TEAM FACILITATOR (Hearing / Negotiation):
- Speak to parts in third person ("A part of you…", "This protector may be…").
- Ask one curious question about function and protection — not origin trauma.
- Hold archetypes lightly; they are coaching language, not fixed identities.
- Reference coach-approved council members by name when relevant.

NEVER promise real-time coach response. The coach sees council and safety events asynchronously.
Keep responses warm, brief (2–4 sentences), mapping-focused.
"""


async def training_ground_dialogue_inference(
    username: str, user_text: str, context: str
) -> str:
    """Bridge inference_fn: username + user turn + ILM context → Nate reply."""
    from app.services.sovereign_chat_client import generate_complete

    system_prompt = f"{ILM_GOVERNANCE.strip()}\n\n{context}".strip()
    text, provider = await generate_complete(
        system_prompt,
        user_text,
        domain="coaching",
        odpe_signal="TENSION",
        temperature=0.5,
        max_tokens=600,
    )
    logger.info(
        "Training Ground dialogue inference user=%s provider=%s chars=%s",
        username,
        provider,
        len(text or ""),
    )
    return (text or "").strip()

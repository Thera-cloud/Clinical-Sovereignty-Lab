"""Per-coach Morning Audio Brief script. TTS via audio_synthesis_service."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def compose_script(
    *,
    coach_name: str = "Coach",
    tasks: Optional[List[Dict[str, Any]]] = None,
    guidance: str = "",
    campaign_day_n: Optional[int] = None,
) -> str:
    parts = [f"Good morning, {coach_name}."]
    open_tasks = [t for t in (tasks or []) if (t.get("status") or "open") == "open"]
    if open_tasks:
        titles = ", ".join((t.get("title") or "task") for t in open_tasks[:5])
        parts.append(f"Open tasks: {titles}.")
    else:
        parts.append("No open client tasks on the board.")
    if (guidance or "").strip():
        parts.append(guidance.strip())
    if campaign_day_n is not None:
        parts.append(f"Campaign day {int(campaign_day_n)}.")
    return " ".join(parts)


async def render_brief_audio(**kwargs: Any) -> Optional[bytes]:
    from app.services.audio_synthesis_service import synthesize

    script = compose_script(**{k: v for k, v in kwargs.items() if k != "voice"})
    return await synthesize(script, voice=kwargs.get("voice") or "alloy")

"""One turn's vault file and journey panel, decided from the original ask.

The explicit tag chooses the picture. A vault photo does not continue the
last scene. A stored journey panel may. The journey switch loads "that
character" only when a panel exists.
"""

from __future__ import annotations

from typing import Any

from app.services.sse_panel_chat_context import (
    _SSE_PANEL_REF_RE,
    _STORY_PANEL_LEGACY_RE,
    build_sse_panel_chat_context,
)
from app.services.vault_chat_context import (
    _VAULT_REF_RE,
    build_vault_chat_context,
    current_vault_kind,
)


async def _journey_switch_on(db_pool, profile: dict[str, Any]) -> bool:
    username = str((profile or {}).get("username") or "").strip()
    if not db_pool or not username or not hasattr(db_pool, "fetchrow"):
        return False
    try:
        row = await db_pool.fetchrow(
            "SELECT theraworld_in_chat FROM main_chat_stride_state WHERE username = $1",
            username,
        )
        return bool(row and row["theraworld_in_chat"])
    except Exception:
        return False


def merge_ask_text(original: str, vault_text: str, panel_text: str) -> str:
    """Keep both rewrites when the client tagged a file and a panel."""
    merged = vault_text if vault_text != original else original
    if panel_text == original:
        return merged
    match = _SSE_PANEL_REF_RE.search(merged)
    if match:
        panel_id = match.group(1)
        return _SSE_PANEL_REF_RE.sub(
            f"(asking about my Sovereign Journey story panel image id:{panel_id})",
            merged,
            count=1,
        ).strip()
    if _STORY_PANEL_LEGACY_RE.search(merged):
        return _STORY_PANEL_LEGACY_RE.sub(
            "(asking about my Sovereign Journey story panel image) ",
            merged,
            count=1,
        ).strip()
    if vault_text == original:
        return panel_text
    return merged


def choose_picture(
    original: str, vault_image: str | None, panel_image: str | None,
) -> tuple[str | None, bool]:
    """Return (image, pixels_are_journey). The explicit tag wins."""
    panel_tagged = bool(_SSE_PANEL_REF_RE.search(original or "") or _STORY_PANEL_LEGACY_RE.search(original or ""))
    vault_tagged = bool(_VAULT_REF_RE.search(original or ""))
    if panel_tagged and panel_image:
        return panel_image, True
    if (vault_tagged or not panel_tagged) and vault_image:
        return vault_image, False
    if panel_image:
        return panel_image, True
    return None, False


async def prepare_vault_and_panel(db_pool, profile: dict[str, Any], user_text: str):
    """Return (user_text, vault_context, image, panel_ctx).

    Failures stay inside each lookup so a vault error still leaves the scene,
    and a scene error still leaves the file.
    """
    original = user_text or ""
    vault_text, vault_context, vault_image = original, "", None
    try:
        vault_text, vault_context, vault_image = await build_vault_chat_context(
            db_pool, profile, original,
        )
    except Exception as exc:
        print(f">>> [VAULT] Injection error (non-fatal): {exc}")
    kind = current_vault_kind()
    journey_open = await _journey_switch_on(db_pool, profile)
    panel_text, panel_ctx, panel_image = original, "", None
    try:
        panel_text, panel_ctx, panel_image = await build_sse_panel_chat_context(
            db_pool, profile, original, journey_open=journey_open, vault_kind=kind,
        )
    except Exception as exc:
        print(f">>> [SSE PANEL] Injection error (non-fatal): {exc}")

    merged = merge_ask_text(original, vault_text, panel_text)
    image, pixels_are_journey = choose_picture(original, vault_image, panel_image)
    if panel_ctx and image and not pixels_are_journey:
        panel_ctx = (
            panel_ctx.rstrip()
            + "\n\n[SCENE NOTES ARE WRITING ONLY] The attached picture is a vault file, "
            "not this journey panel. Do not describe that file as the scene."
        )
    if panel_ctx:
        vault_context = (
            f"{vault_context}\n\n{panel_ctx}".strip() if vault_context else panel_ctx
        )
    return merged, vault_context, image, panel_ctx

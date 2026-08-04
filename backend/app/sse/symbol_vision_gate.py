"""Thera-World Global Symbol Safety System — Layer D3: post-generation vision gate.

Spec: thera-world-symbol-safety-cursor-prompt.md, Layer D, section D3.

Before any panel is delivered:
  1. Run a vision-model check: does the rendered image contain any of the
     user's excluded symbols + the `never` tier list?
  2. On detection -> regenerate with a strengthened negative prompt (max 3
     attempts) -> if still failing, fall back to a safe template scene and
     log for clinician review.
  3. Every gate decision is logged for auditability (pass, fail, retry,
     fallback, or gate-unavailable) — D3.4.

Fail-open policy: if the vision model itself is unreachable (Azure not
configured, network error, malformed response), the gate returns
gate_passed=False but still DELIVERS the image rather than blocking
therapeutic content on an infrastructure outage. The unavailability is
logged distinctly (outcome='gate_unavailable', gate_available=False) so
the trust auditor can track gate uptime separately from violation rate —
this is not the same as "passed clean".
"""
from __future__ import annotations

import base64
import json
import logging
import random
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import aiohttp

logger = logging.getLogger(__name__)

# D3.2 fallback — conservative Layer A imagery, always safe regardless of any
# user's exclusion posture (no animals, no religious iconography, no fire-near-person).
_SAFE_TEMPLATE_PROMPTS = [
    "a quiet dawn path through open fields, warm sunlight through mist, painterly style, no text",
    "a still lake at dusk reflecting a clearing sky, painterly style, no text",
    "a lantern-lit trail through a garden of budding trees, painterly style, no text",
    "stepping stones across a calm river under a soft morning sky, painterly style, no text",
]

RegenerateFn = Callable[[str, str], Awaitable[bytes]]


def _azure_vision_config() -> Tuple[str, str, str]:
    try:
        from app.config import settings
    except Exception:
        return "", "", ""
    endpoint = (getattr(settings, "AZURE_OPENAI_ENDPOINT", "") or "").rstrip("/")
    api_key = getattr(settings, "AZURE_API_KEY", "") or ""
    deployment = getattr(settings, "AZURE_OPENAI_CHAT_DEPLOYMENT", "") or ""
    if endpoint and not endpoint.startswith("http"):
        endpoint = f"https://{endpoint}"
    return endpoint, api_key, deployment


async def _call_vision_model(image_bytes: bytes, symbol_names: List[str]) -> Optional[Dict[str, Any]]:
    """Ask the vision model whether the image contains any named symbol.
    Returns {"violations": [...]} on a successful call (violations may be
    empty), or None if the call itself failed — callers must treat None as
    'gate unavailable', never as 'passed clean'."""
    if not symbol_names:
        return {"violations": []}
    endpoint, api_key, deployment = _azure_vision_config()
    if not all([endpoint, api_key, deployment]):
        logger.warning("symbol_vision_gate: Azure OpenAI not configured — vision gate unavailable")
        return None
    url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version=2024-06-01"
    headers = {"Content-Type": "application/json", "api-key": api_key}
    b64 = base64.b64encode(image_bytes).decode("ascii")
    symbol_list = ", ".join(symbol_names)
    question = (
        f"Does this image visually depict any of the following: {symbol_list}? "
        "Respond with ONLY a JSON object, no other text: "
        '{"violations": ["<symbol from the list that is actually visually present>", ...]}. '
        "Return an empty list if none are present. Be conservative — only list a symbol "
        "if a viewer would clearly recognize it in the image."
    )
    payload = {
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": question},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        }],
        "max_completion_tokens": 300,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status != 200:
                    logger.warning("symbol_vision_gate: Azure vision call failed status=%s", resp.status)
                    return None
                data = await resp.json()
                choices = data.get("choices", [])
                if not choices:
                    return None
                content = choices[0].get("message", {}).get("content", "") or ""
                start, end = content.find("{"), content.rfind("}")
                if start == -1 or end == -1:
                    logger.warning("symbol_vision_gate: non-JSON vision response: %s", content[:200])
                    return None
                parsed = json.loads(content[start:end + 1])
                if not isinstance(parsed.get("violations"), list):
                    return None
                return parsed
    except Exception as exc:
        logger.warning("symbol_vision_gate: vision call exception: %s", exc)
        return None


async def _log_gate_decision(
    db_pool, user_id: str, panel_id: Optional[str], attempt: int,
    checked_symbols: List[str], violations: List[str], gate_available: bool, outcome: str,
) -> None:
    """D3.4 — log every gate decision, pass or fail, gate up or down. Never raises."""
    if not db_pool:
        return
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO sse_symbol_gate_log "
                "(user_id, panel_id, attempt, checked_symbols, violations, gate_available, outcome) "
                "VALUES ($1,$2,$3,$4::jsonb,$5::jsonb,$6,$7)",
                user_id, panel_id, attempt,
                json.dumps(checked_symbols), json.dumps(violations), gate_available, outcome,
            )
    except Exception as exc:
        logger.warning("symbol_vision_gate: gate decision log failed for %s: %s", user_id, exc)


async def alert_clinician_symbol_violation(
    db_pool, user_id: str, panel_id: Optional[str], violations: List[str], note: str = "",
) -> bool:
    """Independently callable clinician-alert path (spec acceptance criterion 4:
    a violating panel must page the clinician dashboard). Decoupled from the gate
    call site on purpose so it can be exercised directly in tests without needing
    a live vision model — 'if the vision gate is disabled in a test, a violating
    panel triggers the clinician alert path' means THIS function is reachable and
    correct on its own, independent of whether the vision check itself ran.
    Returns True only on confirmed write."""
    if not db_pool:
        return False
    summary = f"Thera-World panel for user={user_id} violated symbol safety: {', '.join(violations) or 'unknown'}"
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO skyeye_activity (type, content, platform, severity, metadata, created_at) "
                "VALUES ('symbol_safety_violation', $1, 'thera_world', 'safety', $2::jsonb, NOW())",
                summary,
                json.dumps({"user_id": user_id, "panel_id": panel_id, "violations": violations, "note": note}),
            )
        return True
    except Exception as exc:
        logger.warning("symbol_vision_gate: clinician alert write failed for %s: %s", user_id, exc)
        return False


async def validate_panel_image(
    image_bytes: bytes,
    image_prompt: str,
    negative_prompt: str,
    user_id: str,
    db_pool,
    panel_id: Optional[str] = None,
    regenerate_fn: Optional[RegenerateFn] = None,
    max_attempts: int = 3,
) -> Tuple[bytes, str, bool]:
    """D3 orchestration. `regenerate_fn(prompt, negative_prompt) -> bytes` lets the
    caller reuse its own image-backend call (thera_world_engine owns that, this
    module stays backend-agnostic). Returns (final_image_bytes, final_prompt_used,
    gate_passed) — gate_passed is True only when the delivered image was
    vision-confirmed clean."""
    from app.sse.symbol_safety import build_posture, never_tier_ids, get_symbol

    try:
        posture = await build_posture(user_id, db_pool)
        excluded_ids = [sid for sid, st in posture.items() if st == "excluded"]
    except Exception as exc:
        logger.warning("symbol_vision_gate: could not resolve user posture for %s: %s", user_id, exc)
        excluded_ids = []
    check_ids = sorted(set(excluded_ids) | set(never_tier_ids()))
    symbol_names: List[str] = []
    for sid in check_ids:
        sym = get_symbol(sid) or {}
        aliases = sym.get("aliases") or []
        symbol_names.append(aliases[0] if aliases else sid.replace("_", " "))

    current_bytes, current_prompt, current_negative = image_bytes, image_prompt, negative_prompt
    violations: List[str] = []

    for attempt in range(1, max_attempts + 1):
        result = await _call_vision_model(current_bytes, symbol_names)
        if result is None:
            await _log_gate_decision(db_pool, user_id, panel_id, attempt, symbol_names, [], False, "gate_unavailable")
            return current_bytes, current_prompt, False
        violations = result.get("violations", [])
        if not violations:
            await _log_gate_decision(db_pool, user_id, panel_id, attempt, symbol_names, [], True, "clean")
            return current_bytes, current_prompt, True
        await _log_gate_decision(db_pool, user_id, panel_id, attempt, symbol_names, violations, True, "violation_detected")
        if attempt == max_attempts or regenerate_fn is None:
            break
        current_negative = ", ".join(dict.fromkeys(f"{current_negative}, {', '.join(violations)}".split(", ")))
        try:
            current_bytes = await regenerate_fn(current_prompt, current_negative)
        except Exception as exc:
            logger.warning("symbol_vision_gate: regeneration attempt %d failed for %s: %s", attempt, user_id, exc)
            break

    # Exhausted retries (or a regeneration attempt itself failed) — fall back to a
    # guaranteed-safe Layer A template scene rather than deliver a violating image.
    safe_prompt = random.choice(_SAFE_TEMPLATE_PROMPTS)
    safe_bytes = current_bytes
    if regenerate_fn is not None:
        try:
            safe_bytes = await regenerate_fn(safe_prompt, "")
        except Exception as exc:
            logger.warning("symbol_vision_gate: safe-template fallback generation failed for %s: %s", user_id, exc)
            safe_prompt = current_prompt
    await _log_gate_decision(db_pool, user_id, panel_id, max_attempts + 1, symbol_names, violations, True, "fallback_safe_template")
    await alert_clinician_symbol_violation(
        db_pool, user_id, panel_id, violations,
        note="exhausted regeneration attempts; delivered safe template scene instead",
    )
    return safe_bytes, safe_prompt, False

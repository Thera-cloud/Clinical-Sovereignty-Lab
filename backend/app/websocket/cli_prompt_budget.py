"""
Hard prompt ceilings for nate_cli_chat (and streaming fallbacks).

Chars are a rough proxy for tokens (~4 chars/token). Trim system prompt from the
end so highest-priority content (truth rules first in cli_manifest order) remains.
"""

from __future__ import annotations

import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)

# Provider ceilings (chars). Applied before each provider attempt in generate_streaming.
PROVIDER_PROMPT_CEILINGS = {
    "grok": 48_000,
    "sovereign": 24_000,
    "workers_ai": 48_000,
    "azure": 48_000,
    "home_gpu": 48_000,
    "digitalocean": 24_000,
}

CLI_MAX_HISTORY_CHARS = 8_000

_TRAIL_NOTICE = (
    "\n\n[CONTEXT TRIMMED: System prompt exceeded {provider} ceiling ({ceiling:,} chars). "
    "Original: {orig:,} chars. Kept: {kept:,} chars. "
    "Lowest-priority workspace rules and codebase context were removed. "
    "Use read_file and grep to access codebase information as needed.]"
)


def trim_prompt_to_ceiling(
    system_prompt: str,
    user_message: str,
    provider: str,
    max_response_tokens: int = 2000,
) -> Tuple[str, str]:
    """
    Trim system_prompt so system + user_message fits the provider TTFT/context budget.
    user_message is not shortened (caller's responsibility to window history).
    """
    ceiling = PROVIDER_PROMPT_CEILINGS.get(provider, 32_000)
    response_reserve = max(0, max_response_tokens) * 4
    um_len = len(user_message or "")
    available = ceiling - response_reserve - um_len

    if available <= 256:
        logger.warning(
            "CLI prompt budget: provider=%s user_message very large (%d chars); "
            "clamping system slice to 256+ chars",
            provider,
            um_len,
        )
        available = max(256, min(4096, ceiling // 4))

    if len(system_prompt) <= available:
        return system_prompt, user_message

    trimmed = system_prompt[:available]
    last_nl = trimmed.rfind("\n")
    if last_nl > int(available * 0.9):
        trimmed = trimmed[:last_nl]

    notice = _TRAIL_NOTICE.format(
        provider=provider,
        ceiling=ceiling,
        orig=len(system_prompt),
        kept=len(trimmed),
    )
    trimmed = trimmed + notice

    print(
        f">>> [CLI] Prompt trimmed for {provider}: "
        f"{len(system_prompt):,} → {len(trimmed):,} chars (ceiling: {ceiling:,})",
        flush=True,
    )
    logger.warning(
        "CLI prompt trimmed for provider=%s: system %d → %d chars (ceiling=%d, user_msg=%d)",
        provider,
        len(system_prompt),
        len(trimmed),
        ceiling,
        um_len,
    )
    return trimmed, user_message


def trim_system_for_non_system_budget(
    system_prompt: str,
    non_system_char_len: int,
    provider: str,
    max_response_tokens: int = 2000,
) -> str:
    """
    Trim system only, reserving space for all non-system message bodies (Ollama native FC).
    """
    ceiling = PROVIDER_PROMPT_CEILINGS.get(provider, 32_000)
    response_reserve = max(0, max_response_tokens) * 4
    available = ceiling - response_reserve - max(0, non_system_char_len)

    if available <= 256:
        available = max(256, min(4096, ceiling // 4))

    if len(system_prompt) <= available:
        return system_prompt

    trimmed = system_prompt[:available]
    last_nl = trimmed.rfind("\n")
    if last_nl > int(available * 0.9):
        trimmed = trimmed[:last_nl]
    trimmed = trimmed + _TRAIL_NOTICE.format(
        provider=provider,
        ceiling=ceiling,
        orig=len(system_prompt),
        kept=len(trimmed),
    )
    logger.warning(
        "CLI Ollama path: system trimmed %d → %d chars (non_system=%d ceiling=%d)",
        len(system_prompt),
        len(trimmed),
        non_system_char_len,
        ceiling,
    )
    return trimmed


def window_cli_conversation_history(messages: List[dict], max_chars: int = CLI_MAX_HISTORY_CHARS) -> List[dict]:
    """
    Sliding window over chat messages **excluding** the system prompt message.

    Pass conversation[1:] only. Keeps the first history message (original user task),
    fills middle from newest backward, keeps last 3 messages, inserts a marker if trimmed.
    """
    if not messages:
        return messages

    def _content_len(m: dict) -> int:
        return len(m.get("content") or "")

    total = sum(_content_len(m) for m in messages)
    if total <= max_chars:
        return messages

    if len(messages) == 1:
        m = dict(messages[0])
        c = m.get("content") or ""
        if len(c) > max_chars:
            m["content"] = c[: max(0, max_chars - 80)] + "\n…(truncated)"
        return [m]

    # first = original user/task message; recent = last up to 3 turns
    first = [messages[0]]
    recent = messages[-3:] if len(messages) > 3 else messages[1:]

    used = sum(_content_len(m) for m in first) + sum(_content_len(m) for m in recent)
    remaining = max_chars - used

    if remaining <= 0:
        budget = max_chars - sum(_content_len(m) for m in first)
        pruned_recent: List[dict] = []
        for m in reversed(recent):
            c = m.get("content") or ""
            role = m.get("role", "user")
            if budget <= 0:
                break
            if len(c) <= budget:
                pruned_recent.insert(0, dict(m))
                budget -= len(c)
            else:
                pruned_recent.insert(
                    0,
                    {"role": role, "content": (c[-budget:] if budget > 40 else c[:budget]) + "\n…(trimmed)"},
                )
                budget = 0
        out = list(first) + pruned_recent
        if len(out) < len(messages):
            omitted = max(0, len(messages) - len(out))
            out.insert(1, {
                "role": "user",
                "content": (
                    f"[{omitted} earlier turns trimmed. Use tool calls to re-read any files from earlier turns.]"
                ),
            })
        return out

    middle: List[dict] = []
    if len(messages) > 4:
        for msg in reversed(messages[1:-3]):
            msg_len = _content_len(msg)
            if remaining - msg_len < 0:
                break
            middle.insert(0, dict(msg))
            remaining -= msg_len

    windowed = list(first) + middle + list(recent)
    if len(windowed) < len(messages):
        omitted = len(messages) - len(windowed)
        windowed.insert(1, {
            "role": "user",
            "content": (
                f"[{omitted} earlier turns omitted. Use tool calls to re-read files from earlier turns.]"
            ),
        })
    return windowed

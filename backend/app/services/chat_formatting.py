"""Big Nate Chat message formatting helpers."""

from __future__ import annotations

import re
from typing import List


def normalize_chat_readability(text: str) -> str:
    """Expand jammed markdown tables into spaced blocks for SkyEye chat UI."""
    if not text or "|" not in text:
        return text

    if len(re.findall(r"\|\s*\d+\s*\|", text)) >= 2:
        text = re.sub(r"\s*(?=\|\s*\d+\s*\|)", "\n\n", text)

    out_lines: List[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if re.match(r"^\|\s*[-: ]+\|", stripped):
            continue
        row = re.match(
            r"^\|\s*(\d+)\s*\|\s*([^|]+?)\|\s*([A-Z]{3,5})\s*\|\s*(.+?)\s*\|?\s*$",
            stripped,
            re.IGNORECASE,
        )
        if row:
            day, slot_time, lane, body = row.groups()
            out_lines.append(
                f"DAY {day} — {slot_time.strip()} — {lane.strip().upper()}\n\n{body.strip()}"
            )
            out_lines.append("")
            continue
        out_lines.append(line)

    normalized = "\n".join(out_lines)
    normalized = re.sub(r"\n{4,}", "\n\n\n", normalized)
    return normalized.strip()
